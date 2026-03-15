import os
import time
from dataclasses import dataclass

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright


BASE_URL = os.getenv("ODOO_URL", "https://elegomotors-14mar-sheet-29703464.dev.odoo.com")
DATABASE = os.getenv("ODOO_DB", "elegomotors")
SCREENSHOTS_DIR = os.getenv("EGO_SCREENSHOTS_DIR", "logs/screenshots")
SCREENSHOTS_ENABLED = os.getenv("EGO_SCREENSHOTS", "0") == "1"
HEADLESS = os.getenv("PW_HEADLESS", "0") == "1"


@dataclass(frozen=True)
class UserCred:
    key: str
    name: str
    login: str
    password: str


USERS = {
    "manohar": UserCred("manohar", "Manohar Kalbhor", "manohar.kalbhor@elegomotors.com", "manohar@123"),
    "amit": UserCred("amit", "Amit Kale", "storeelegomotors@gmail.com", "amitkale@123"),
    "prashant": UserCred("prashant", "Prashant Khedkar", "NPD@elegomotors.com", "prashant@123"),
    "rajshri": UserCred("rajshri", "Rajshri Kadam", "elegoac@gmail.com", "rajshri@123"),
    "srushti": UserCred("srushti", "Srushti Gund", "hrelegomotors@gmail.com", "srusti@123"),
    "pratik": UserCred("pratik", "Pratik Gund", "quality.elego23@gmail.com", "pratik@123"),
    "tushar": UserCred("tushar", "Tushar Gaikwad", "leads@elegomotors.com", "tushar@123"),
}


def _stamp() -> str:
    return str(int(time.time()))


class OdooTestHelper:
    def __init__(self, page):
        self.page = page
        self._current_user: str | None = None
        if SCREENSHOTS_ENABLED:
            os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    async def screenshot(self, name: str) -> None:
        if not SCREENSHOTS_ENABLED:
            return
        await self.page.screenshot(path=f"{SCREENSHOTS_DIR}/{_stamp()}_{name}.png", full_page=True)

    async def goto(self, path: str = "/web") -> None:
        await self.page.goto(f"{BASE_URL}{path}")
        await self.page.wait_for_load_state("domcontentloaded")

    async def _handle_user_chooser(self) -> None:
        """Click 'Use another user' if Odoo shows the cached-session chooser dialog.

        After clicking, waits for the login input to become visible so the caller
        can fill credentials immediately without an extra wait.
        """
        try:
            link = self.page.locator(
                "a:has-text('Use another user'), "
                "a:has-text('use another account'), "
                "button:has-text('Use another user')"
            )
            await link.first.wait_for(state="visible", timeout=4000)
            await link.first.click()
            # Wait for the chooser to disappear and the actual login form to appear
            await self.page.wait_for_selector(
                'input[name="login"]', state="visible", timeout=10000
            )
        except Exception:
            pass  # Chooser not present — normal login form already visible

    async def login_as(self, user_key: str) -> UserCred:
        user = USERS[user_key]
        if self._current_user == user_key:
            # Already logged in — just navigate home to get a clean page state.
            await self.page.goto(f"{BASE_URL}/odoo")
            await self.page.wait_for_selector(".o_main_navbar", timeout=15000)
            await self.dismiss_popups()
            return user

        # Explicitly logout the current session before switching users so
        # Odoo does not accumulate cached sessions that trigger the chooser.
        if self._current_user is not None:
            try:
                await self.goto("/web/session/logout")
                await self.page.wait_for_load_state("domcontentloaded")
            except Exception:
                pass

        await self.goto("/web/login")
        # Handle the "Choose a user" dialog that Odoo shows when multiple
        # sessions are cached in the browser's localStorage.
        await self._handle_user_chooser()
        # Fallback wait — ensures the form is visible even if _handle_user_chooser
        # returned early (chooser was not present or already dismissed).
        await self.page.wait_for_selector('input[name="login"]', state="visible", timeout=15000)

        await self.page.fill('input[name="login"]', user.login)
        await self.page.fill('input[name="password"]', user.password)
        db_input = self.page.locator('input[name="db"]')
        if await db_input.count():
            await db_input.fill(DATABASE)
        await self.page.click('button[type="submit"]')
        await self.page.wait_for_selector(".o_main_navbar", timeout=20000)
        await self.dismiss_popups()
        self._current_user = user_key
        await self.screenshot(f"login_{user.key}")
        return user

    async def logout(self) -> None:
        self._current_user = None
        await self.goto("/web/session/logout")
        await self.page.wait_for_selector('input[name="login"]', timeout=10000)

    async def dismiss_popups(self) -> None:
        candidates = [
            '.o_tour_pointer_tip button',
            'button.btn-close',
            '.modal-footer button.btn-secondary',
            # Dismiss Odoo technical/warning modals (e.g. info dialogs during transfers)
            '.o_technical_modal .modal-footer button.btn-primary',
            '.o_technical_modal .modal-footer button:has-text("Ok")',
            '.o_technical_modal .modal-footer button:has-text("OK")',
            '.o_technical_modal button.btn-close',
        ]
        for selector in candidates:
            try:
                if await self.page.locator(selector).first.is_visible(timeout=500):
                    await self.page.locator(selector).first.click()
                    await self.page.wait_for_timeout(300)
            except Exception:
                pass

    async def open_menu_url(self, relative_url: str) -> None:
        await self.goto(relative_url)
        await self.page.wait_for_load_state("domcontentloaded")
        if "Missing Action" in await self.page.content():
            raise AssertionError(f"Invalid Odoo route/action: {relative_url}")

    async def click_if_visible(self, selector: str, timeout: int = 2000) -> bool:
        try:
            locator = self.page.locator(selector).first
            await locator.wait_for(state="visible", timeout=timeout)
            await locator.click()
            await self.page.wait_for_timeout(400)
            return True
        except Exception:
            return False

    async def require_click(self, selector: str, timeout: int = 2000) -> None:
        if not await self.click_if_visible(selector, timeout=timeout):
            raise AssertionError(f"Required click target not available: {selector}")

    async def require_click_any(self, selectors: list[str], timeout: int = 2000) -> None:
        for selector in selectors:
            if await self.click_if_visible(selector, timeout=timeout):
                return
        current_url = self.page.url
        raise AssertionError(
            f"Required click target not available for selectors: {selectors}; url={current_url}"
        )

    async def assert_text_visible(self, text: str) -> None:
        await self.page.locator(f"text={text}").first.wait_for(timeout=10000)

    async def assert_text_not_visible(self, text: str) -> None:
        assert await self.page.locator(f"text={text}").count() == 0

    async def assert_no_missing_action(self) -> None:
        assert "Missing Action" not in await self.page.content()

    async def _clear_search_filters(self) -> None:
        """Remove all active search facets/filters from the search bar."""
        for remove_btn in await self.page.locator(
            ".o_searchview_facet .o_facet_remove, "
            ".o_searchview_facet button, "
            "button[title='Remove filter']"
        ).all():
            try:
                await remove_btn.click()
                await self.page.wait_for_timeout(200)
            except Exception:
                pass

    async def open_inventory_transfers(self) -> None:
        """Navigate to the Inventory Overview page (the picking-types hub in Odoo 17).

        In Odoo 17, there is no standalone 'All Transfers' menu item.
        The Overview shows cards for every operation type; use
        open_picking_type_transfers() to go to a specific type's list.
        """
        await self.open_menu_url("/odoo/inventory")
        await self.page.wait_for_timeout(800)

    async def open_picking_type_transfers(self, operation_type_name: str) -> None:
        """Navigate to the transfers list for a specific operation type.

        Finds the matching card on the Inventory Overview and opens its
        full transfer list (all statuses, not just Ready).
        """
        await self.open_menu_url("/odoo/inventory")
        await self.page.wait_for_timeout(800)

        # Find the article card whose text contains the operation type name
        card = self.page.locator("article").filter(has_text=operation_type_name).first
        try:
            await card.wait_for(state="visible", timeout=6000)
        except Exception:
            raise AssertionError(
                f"Could not find Inventory Overview card for operation type: '{operation_type_name}'"
            )

        # Prefer the "Open" button – it opens all transfers for that type
        open_btn = card.locator(
            "button:has-text('Open'), "
            "button[name='get_action_picking_tree_ready'], "
            "button[name='get_action_picking_tree_all']"
        )
        if await open_btn.count() > 0:
            await open_btn.first.click()
        else:
            # Fallback: click the link title on the card
            await card.locator("a").first.click()

        await self.page.wait_for_timeout(800)

        # Remove any automatic "Ready" status filter so we see all transfers
        await self._clear_search_filters()
        await self.page.wait_for_timeout(400)

    async def open_inventory_products(self) -> None:
        await self.open_menu_url("/odoo/inventory")
        await self.require_click_any([
            'a[data-menu-xmlid="stock.menu_stock_root"]',
            "button:has-text('Products')",
            "text=Products",
        ], timeout=5000)
        await self.require_click_any([
            'a[data-menu-xmlid="stock.menu_stock_products_menu"]',
            "a:has-text('Products')",
            "button:has-text('Products')",
            "text=Products",
        ], timeout=5000)

    async def open_account_moves(self) -> None:
        await self.open_menu_url("/odoo/accounting")
        await self.require_click('a[data-menu-xmlid="account.menu_action_move_out_invoice_type"]', timeout=5000)

    async def open_customer_invoices(self) -> None:
        """Navigate to Accounting > Customers > Invoices."""
        await self.open_menu_url("/odoo/accounting")
        await self.page.wait_for_timeout(500)
        await self.require_click_any([
            "button:has-text('Customers')",
            "a:has-text('Customers')",
        ], timeout=5000)
        await self.page.wait_for_timeout(300)
        await self.require_click_any([
            "menuitem:has-text('Invoices')",
            "a:has-text('Invoices')",
            "text=Invoices",
        ], timeout=5000)
        await self.page.wait_for_timeout(600)

    async def open_vendor_bills(self) -> None:
        """Navigate to Vendor Bills.

        Tries the direct URL first — users with only account.group_account_invoice
        (Billing) do not get the 'Vendors' top menu in Accounting, but can still
        access the vendor bills action URL directly.  Falls back to menu navigation
        for users with full Accountant / Manager access.
        """
        # Try the direct route first
        await self.open_menu_url("/odoo/accounting/vendor-bills")
        await self.page.wait_for_timeout(500)
        if "Missing Action" not in await self.page.content():
            return
        # Fallback: navigate through the Vendors menu (Accountant users)
        await self.open_menu_url("/odoo/accounting")
        await self.page.wait_for_timeout(500)
        await self.require_click_any([
            "button:has-text('Vendors')",
            "a:has-text('Vendors')",
        ], timeout=5000)
        await self.page.wait_for_timeout(300)
        await self.require_click_any([
            "menuitem:has-text('Bills')",
            "a:has-text('Bills')",
            "text=Bills",
        ], timeout=5000)
        await self.page.wait_for_timeout(600)

    async def open_inventory_configuration(self) -> None:
        await self.open_menu_url("/odoo/inventory")
        await self.page.wait_for_timeout(600)
        await self.require_click_any([
            "button:has-text('Configuration')",
            "a[data-menu-xmlid='stock.menu_stock_config_settings']",
            "a:has-text('Configuration')",
            "text=Configuration",
        ], timeout=6000)

    async def open_inventory_locations(self) -> None:
        """Navigate to Inventory > Configuration > Locations.

        In Odoo 17 the Locations menu item only appears when 'Storage
        Locations' is enabled.  We try the menu first, then fall back to
        the known action URL pattern.
        """
        await self.open_inventory_configuration()
        found = await self.click_if_visible(
            "menuitem:has-text('Locations'), "
            "a:has-text('Locations'), "
            "button:has-text('Locations'), "
            "text=Locations",
            timeout=4000,
        )
        if not found:
            # Fallback: use Odoo's action external-id URL format
            await self.goto("/odoo/inventory")
            await self.page.wait_for_timeout(600)
            # Trigger via JS service (works in Odoo 17 owl apps)
            await self.page.evaluate("""
                async () => {
                    const apps = window.__owl__ && window.__owl__.apps;
                    if (apps && apps.size) {
                        const app = [...apps][0];
                        if (app && app.env && app.env.services && app.env.services.action) {
                            await app.env.services.action.doAction('stock.action_location_form');
                            return;
                        }
                    }
                }
            """)
            await self.page.wait_for_timeout(1500)
            # If still not on locations page, raise
            if "Locations" not in await self.page.title() and "location" not in self.page.url.lower():
                raise AssertionError("Could not navigate to Locations page")

    async def open_inventory_operation_types(self) -> None:
        await self.open_inventory_configuration()
        # In Odoo 17 the menu item is "Operations Types" (plural)
        await self.require_click_any([
            "menuitem:has-text('Operations Types')",
            "menuitem:has-text('Operation Types')",
            "a:has-text('Operations Types')",
            "a:has-text('Operation Types')",
            "button:has-text('Operations Types')",
            "button:has-text('Operation Types')",
            "text=Operations Types",
            "text=Operation Types",
        ], timeout=5000)

    async def open_inventory_warehouses(self) -> None:
        await self.open_inventory_configuration()
        await self.require_click_any([
            "menuitem:has-text('Warehouses')",
            "a:has-text('Warehouses')",
            "button:has-text('Warehouses')",
            "text=Warehouses",
        ], timeout=5000)

    async def _handle_validate_dialogs(self) -> None:
        """Handle any dialogs that appear after clicking Validate on a transfer."""
        await self.page.wait_for_timeout(800)
        # "Immediate Transfer" dialog
        for btn_text in ["Validate", "Apply All"]:
            if await self.click_if_visible(
                f".modal button:has-text('{btn_text}'), "
                f".o_dialog button:has-text('{btn_text}')",
                timeout=2500,
            ):
                await self.page.wait_for_timeout(600)
                break
        # "Create Backorder?" dialog
        for btn_text in ["No Backorder", "No Transfer"]:
            if await self.click_if_visible(
                f".modal button:has-text('{btn_text}'), "
                f".o_dialog button:has-text('{btn_text}')",
                timeout=2500,
            ):
                await self.page.wait_for_timeout(600)
                break

    async def create_simple_internal_transfer(
        self,
        operation_type: str,
        product_name: str,
        qty: str,
        src_location: str,
        dest_location: str,
    ) -> None:
        """Create and validate a stock transfer.

        Navigates to the specific operation type's transfers list via the
        Inventory Overview card, clicks New, fills product/qty (locations
        are pre-configured on the operation type), then validates.
        """
        await self.open_picking_type_transfers(operation_type)
        await self.require_click(
            "button.o_list_button_add, button[name='action_picking_new']",
            timeout=8000,
        )
        await self.page.wait_for_timeout(800)

        # Operation type may already be set; fill only if field is empty/editable
        op_field = self.page.locator('div[name="picking_type_id"] input')
        if await op_field.count() > 0:
            try:
                val = await op_field.first.input_value()
                if not (val or "").strip():
                    await op_field.first.click()
                    await self.page.fill('div[name="picking_type_id"] input', operation_type)
                    await self.page.keyboard.press("ArrowDown")
                    await self.page.keyboard.press("Enter")
                    await self.page.wait_for_timeout(400)
            except Exception:
                pass

        # Locations are typically pre-configured; fill only when the field is blank
        for field_name, location_val in [
            ("location_id", src_location),
            ("location_dest_id", dest_location),
        ]:
            field = self.page.locator(f'div[name="{field_name}"] input')
            if await field.count() > 0:
                try:
                    val = await field.first.input_value()
                    if not (val or "").strip():
                        await field.first.click()
                        await field.first.fill(location_val)
                        await self.page.keyboard.press("ArrowDown")
                        await self.page.keyboard.press("Enter")
                        await self.page.wait_for_timeout(300)
                except Exception:
                    pass

        # Add a product line (Odoo 17 uses <button>, older versions use <a>)
        added_line = False
        for selector in [
            "a.o_field_x2many_list_row_add",
            "button:has-text('Add a line')",
            "a:has-text('Add a line')",
            "button:has-text('Add a product')",
            ".o_field_x2many_list_row_add",
            "button[class*='x2many']",
            "table button:has-text('Add')",
        ]:
            if await self.click_if_visible(selector, timeout=2000):
                added_line = True
                break
        if not added_line:
            raise AssertionError("Could not find button to add product line")
        await self.page.wait_for_timeout(300)
        prod_field = self.page.locator('div[name="product_id"] input')
        if await prod_field.count() > 0:
            await prod_field.first.click()
            await prod_field.first.fill(product_name)
            await self.page.wait_for_timeout(500)
            await self.page.keyboard.press("ArrowDown")
            await self.page.keyboard.press("Enter")
            await self.page.wait_for_timeout(500)

        # Dismiss any technical modal that may have appeared during product selection
        await self.dismiss_popups()
        await self.page.wait_for_timeout(300)

        # Set quantity (demand or done field)
        qty_field = self.page.locator(
            'div[name="quantity"] input, div[name="product_uom_qty"] input, div[name="qty_done"] input'
        )
        if await qty_field.count() > 0:
            await qty_field.first.click()
            await self.page.keyboard.press("Control+A")
            await self.page.keyboard.type(qty)
            await self.page.keyboard.press("Tab")
            await self.page.wait_for_timeout(300)

        # Validate
        await self.require_click('button[name="button_validate"]', timeout=5000)
        await self._handle_validate_dialogs()
        await self.assert_text_visible("Done")
        await self.screenshot(f"transfer_{operation_type.lower().replace(' ', '_')}")

    async def chatter_contains(self, expected_text: str) -> None:
        """Check that the chatter / message thread contains the given text."""
        # Try to locate the chatter container (several selector variants for different Odoo 17 builds)
        chatter_selectors = [
            ".o-mail-Thread",
            ".o-mail-Chatter",
            ".o_Chatter",
            ".o_mail_thread",
            ".o_mail_chatter",
            "[class*='mail-Thread']",
            "[class*='Chatter']",
        ]

        for selector in chatter_selectors:
            try:
                loc = self.page.locator(selector).first
                await loc.wait_for(state="visible", timeout=5000)
                break
            except Exception:
                pass

        # Poll page content for expected text (max 12 s)
        deadline = time.time() + 12
        while time.time() < deadline:
            if expected_text in await self.page.content():
                return
            await self.page.wait_for_timeout(400)
        raise AssertionError(
            f"Chatter text '{expected_text}' not found; url={self.page.url}"
        )

    async def followers_contains(self, expected_name: str) -> None:
        """Check that expected_name is a visible follower on the current record."""
        await self.page.wait_for_timeout(300)

        # Try to click the followers button to open the panel
        for selector in [
            "button[class*='Followers'], button[class*='followers']",
            ".o-mail-Followers-button",
            "button.o_followers_count",
            ".o_mail_followers button",
            "button:has-text('Followers')",
        ]:
            if await self.click_if_visible(selector, timeout=2000):
                break

        await self.page.wait_for_timeout(600)

        # Check page content for the follower name
        deadline = time.time() + 10
        while time.time() < deadline:
            page_content = await self.page.content()

            if expected_name in page_content:
                is_in_modal = ".modal" in page_content or ".o_dialog" in page_content
                is_in_follower_section = "follower" in page_content.lower() or "Following" in page_content

                if is_in_follower_section or is_in_modal:
                    elements = self.page.locator(f"text={expected_name}")
                    count = await elements.count()
                    for i in range(count):
                        try:
                            if await elements.nth(i).is_visible(timeout=300):
                                elem = elements.nth(i)
                                parent_html = await elem.locator("..").inner_html()
                                if "oe_topbar_name" not in parent_html:
                                    return
                        except Exception:
                            pass

            await self.page.wait_for_timeout(400)

        raise AssertionError(
            f"Follower '{expected_name}' not found in followers; url={self.page.url}"
        )

    async def ensure_no_button(self, selector: str) -> None:
        assert await self.page.locator(selector).count() == 0


# Session-scoped fixtures: one browser + one page for the entire test run.
# login_as() caches the current user and skips the login form when the same
# user is requested again, cutting per-test overhead from ~15 s to ~2 s.
@pytest_asyncio.fixture(scope="session")
async def browser():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=HEADLESS, timeout=30000)
    yield browser
    try:
        await browser.close()
    except Exception:
        pass
    try:
        await playwright.stop()
    except Exception:
        pass


@pytest_asyncio.fixture(scope="session")
async def page(browser):
    context = await browser.new_context(viewport={"width": 1920, "height": 1080})
    page = await context.new_page()
    yield page
    await context.close()


@pytest.fixture(scope="session")
def helper(page):
    return OdooTestHelper(page)


@pytest.fixture(scope="session")
def shared_state():
    return {}

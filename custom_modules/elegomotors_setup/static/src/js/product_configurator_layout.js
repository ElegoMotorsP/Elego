/** @odoo-module **/

/**
 * ElegoMotors — Product Configurator: horizontal radio button layout
 *
 * Odoo 18's product configurator renders Color/Side Guards/Battery Type
 * radio options vertically (flex-column). CSS !important can't reliably
 * override this due to cascade order. Instead, we apply inline styles
 * with setProperty('important') which beats any stylesheet rule.
 *
 * Strategy: MutationObserver watches for .o_dialog to appear, then
 * finds each radio group (container of 2+ radio inputs) and converts
 * its flex direction to row with wrap.
 */

function makeRowFlex(el) {
    el.style.setProperty("display", "flex", "important");
    el.style.setProperty("flex-direction", "row", "important");
    el.style.setProperty("flex-wrap", "wrap", "important");
    el.style.setProperty("gap", "8px 20px", "important");
    el.style.setProperty("align-items", "center", "important");
}

function fixRadioGroups(dialog) {
    const seen = new Set();
    for (const input of dialog.querySelectorAll('input[type="radio"]')) {
        const container = input.parentElement && input.parentElement.parentElement;
        if (!container || seen.has(container)) continue;
        seen.add(container);
        if (container.querySelectorAll('input[type="radio"]').length < 2) continue;
        // Skip if already fixed
        if (container.style.getPropertyValue("flex-direction") === "row") continue;
        makeRowFlex(container);
        for (const child of container.children) {
            child.style.setProperty("flex", "0 0 auto", "important");
            child.style.setProperty("width", "auto", "important");
            child.style.setProperty("margin-bottom", "0", "important");
            child.style.setProperty("white-space", "nowrap", "important");
        }
    }
}

const configObserver = new MutationObserver(() => {
    const dialog = document.querySelector(".o_dialog");
    if (!dialog || !dialog.querySelector('input[type="radio"]')) return;
    fixRadioGroups(dialog);
});

function startObserver() {
    if (document.body) {
        configObserver.observe(document.body, { childList: true, subtree: true });
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startObserver);
} else {
    startObserver();
}

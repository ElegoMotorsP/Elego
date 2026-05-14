/** @odoo-module **/

/**
 * ElegoMotors — Product Configurator: horizontal radio button layout
 *
 * Inline style.setProperty with 'important' priority beats any stylesheet
 * rule regardless of load order, making this more reliable than CSS.
 *
 * For each radio name-group (Color, Side Guards, Battery Type), we walk UP
 * the DOM from the input until we find the smallest container that holds
 * all the same-name inputs, then apply flex-row to that container.
 */

function makeRowFlex(el) {
    el.style.setProperty("display", "flex", "important");
    el.style.setProperty("flex-direction", "row", "important");
    el.style.setProperty("flex-wrap", "wrap", "important");
    el.style.setProperty("gap", "8px 24px", "important");
    el.style.setProperty("align-items", "center", "important");
}

function findGroupContainer(firstInput, inputName) {
    // Walk up from the input's parent until we find an element
    // that contains 2+ radio inputs with the same name.
    const selector = inputName
        ? 'input[type="radio"][name="' + inputName.replace(/"/g, '\\"') + '"]'
        : 'input[type="radio"]';
    let el = firstInput.parentElement;
    while (el) {
        if (el.classList && (el.classList.contains("o_dialog") || el.classList.contains("modal"))) break;
        if (el === document.body) break;
        const found = el.querySelectorAll(selector);
        if (found.length >= 2) return el;
        el = el.parentElement;
    }
    return null;
}

function fixRadioGroups(dialog) {
    // Group all radio inputs by their name attribute
    const byName = new Map();
    for (const input of dialog.querySelectorAll('input[type="radio"]')) {
        const name = input.getAttribute("name") || "__unnamed__";
        if (!byName.has(name)) byName.set(name, input);
    }

    for (const [name, firstInput] of byName) {
        const inputName = name === "__unnamed__" ? null : name;
        const container = findGroupContainer(firstInput, inputName);
        if (!container) continue;
        // Skip if already converted
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

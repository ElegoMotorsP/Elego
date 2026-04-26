/** @odoo-module **/

/**
 * ElegoMotors — Barcode Capture Wizard: auto-advance + beep
 *
 * When Prashant scans a barcode in the component capture wizard, the scanner
 * sends barcode text followed by an Enter keystroke. This listener:
 *   1. Intercepts that Enter key (only inside the barcode wizard dialog)
 *   2. Plays a short confirmation beep via Web Audio API
 *   3. Moves focus to the next input field automatically
 *
 * This avoids the need for Prashant to click/tab between the 3 barcode fields.
 */

function playBeep() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = "sine";
        osc.frequency.value = 880;
        gain.gain.setValueAtTime(0.4, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.15);
    } catch (e) {
        console.warn("ElegoMotors barcode: Web Audio unavailable", e);
    }
}

// Capture Enter on barcode wizard inputs and auto-advance to next field.
// Uses capture phase (true) so this runs before Odoo's own Enter handlers.
document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;

    // Only act when our barcode wizard dialog is open
    const dialog = document.querySelector(".o_dialog");
    if (!dialog) return;
    if (!dialog.querySelector('[name="x_motor_serial"], [name="x_battery_serial"], [name="x_controller_serial"]')) return;

    const active = document.activeElement;
    if (!active || active.tagName !== "INPUT") return;

    // Collect all enabled, non-readonly inputs inside the dialog
    const inputs = [...dialog.querySelectorAll("input:not([disabled]):not([readonly])")];
    const idx = inputs.indexOf(active);

    // If this is not the last field, advance to next; otherwise let form handle it
    if (idx < 0 || idx >= inputs.length - 1) return;

    ev.stopPropagation();
    ev.preventDefault();
    playBeep();

    setTimeout(() => {
        inputs[idx + 1].focus();
        inputs[idx + 1].select();
    }, 10);
}, true);

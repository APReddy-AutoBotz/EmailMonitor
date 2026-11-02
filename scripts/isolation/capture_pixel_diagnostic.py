"""Value-free synthetic browser failure categories; never emit guest data."""

import test_operator_capture_pixels as target

# Exact fixed strings only. Unknown exceptions never contribute their text.
REASONS = {
    "capture_shape_refused": 21,
    "capture_mask_install_refused": 22,
    "capture_geometry_refused": 23,
    "capture_state_focus": 24,
    "capture_mask_outside": 25,
    "capture_mutated": 26,
    "Synthetic focus overlap unavailable": 27,
    "Synthetic evidence focus unavailable": 28,
    "Synthetic evidence focus changed": 29,
    "Synthetic focus exposure unavailable": 30,
    "Synthetic focus restoration unavailable": 31,
    "Synthetic focus pixels unavailable": 32,
    "Synthetic focus pixel oracle refused": 33,
    "Synthetic independent pixel oracle refused": 34,
    "Synthetic independent pixel oracle unavailable": 35,
    "Synthetic refusal category refused": 36,
    "Synthetic refusal phase refused": 37,
    "Synthetic focus refusal category refused": 38,
    "Synthetic focus refusal missing": 39,
    "Synthetic focus refusal emitted output": 40,
    "Synthetic fault not applied": 41,
    "Synthetic owned sheet remained": 42,
    "Synthetic foreign sheet was not preserved": 43,
    "Synthetic capture frame refused": 44,
    "Synthetic exposure was not established": 45,
    "Synthetic exposure was not established and restored": 46,
    "Synthetic PNG row format refused": 47,
    "Synthetic pixel redaction refused": 48,
    "Synthetic PNG dimensions refused": 49,
    "Synthetic focus fault unavailable": 50,
    "Synthetic fault unavailable": 51,
    "Synthetic refusal missing": 52,
    "Synthetic refusal emitted output": 53,
    "Synthetic exposure evidence missing": 54,
    "Synthetic control was not established": 55,
    "Pinned Chromium required": 56,
    "Chromium sandbox must remain enabled": 57,
}
UNKNOWN = 59
FAULTS = {
    "preexisting": 60,
    "removed": 61,
    "disabled": 62,
    "mutated": 63,
    "foreign": 64,
    "replaced": 65,
    "unexpected": 66,
    "detached": 67,
    "cleanup": 68,
    "wrong_text": 69,
    "extra_dialog": 70,
    "active_other": 71,
    "animation": 72,
    "opacity_override": 73,
}
FAULT_REASONS = {36, 37, 38, 39, 40, 41, 42, 43, 50, 51, 52, 53}


def category(error: BaseException, fault: object = None) -> int:
    if type(error) not in (ValueError, RuntimeError) or len(error.args) != 1:
        return UNKNOWN
    value = error.args[0]
    reason = REASONS.get(value, UNKNOWN) if type(value) is str else UNKNOWN
    if reason in FAULT_REASONS and type(fault) is str:
        return FAULTS.get(fault, reason)
    return reason


def run() -> None:
    failure = [UNKNOWN]
    original = target.exercise

    async def observed() -> None:
        try:
            await original()
        except BaseException as error:  # noqa: BLE001 - retain only a fixed category
            fault: object = None
            frame = error.__traceback__
            for _ in range(32):
                if frame is None:
                    break
                code = frame.tb_frame.f_code
                if (
                    code.co_filename == "/app/test_operator_capture_pixels.py"
                    and code.co_name == "exercise"
                ):
                    fault = frame.tb_frame.f_locals.get("fault")
                    break
                frame = frame.tb_next
            failure[0] = category(error, fault)
            raise

    target.exercise = observed
    try:
        target.test_actual_sandboxed_chromium_redacts_temporarily_exposed_synthetic_values()
    except BaseException:  # noqa: BLE001 - emit only a fixed process exit category
        raise SystemExit(failure[0]) from None
    finally:
        target.exercise = original


if __name__ == "__main__":
    run()

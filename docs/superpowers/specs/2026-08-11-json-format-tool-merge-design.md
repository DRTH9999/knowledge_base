# JSON Format Tool Merge Design

## Goal

Provide a standalone replacement module that preserves the existing `json_format(data)` API while serializing both MongoDB `ObjectId` values and common NumPy values.

## Scope

- Convert `ObjectId` to `str`.
- Convert `np.integer` to `int`, `np.floating` to `float`, and `np.ndarray` to nested Python lists.
- Preserve `ensure_ascii=False` and `indent=4` output behavior.
- Delegate unsupported values to `json.JSONEncoder.default` so callers receive `TypeError` rather than a lossy string conversion.

## Non-goals

- Do not add support for unrelated special types such as `datetime`, `Decimal`, or `set`.
- Do not replace either existing `json_format_tool.py` until a target path is explicitly selected.

## Verification

Test standard nested data, `ObjectId`, NumPy integer and floating scalars, NumPy arrays, and confirm that an unsupported `set` still raises `TypeError`.

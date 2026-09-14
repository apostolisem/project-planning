"""Planning-issue detection for first-class dependencies (finish-to-start)."""
from __future__ import annotations


def _label(obj) -> str:
    fallback = "Event" if obj.kind == "circle" else obj.kind.title()
    return (obj.text or fallback).strip() or fallback


def compute_issues(model, ignored: set[str] | None = None) -> list[dict]:
    """Return detected dependency issues.

    Each issue: {key, type, title, detail, object_id, blocked: bool}.
    `key` is stable so it can be persisted in model.ignored_issues.
    """
    issues: list[dict] = []
    objects = {obj.id: obj for obj in model.objects.values()}

    for obj in model.objects.values():
        for pred_id in getattr(obj, "predecessors", []) or []:
            key = f"dep:{pred_id}->{obj.id}"
            if pred_id == obj.id:
                issues.append({
                    "key": key,
                    "type": "Self reference",
                    "title": f"{_label(obj)} depends on itself",
                    "detail": "Remove the self-referential predecessor.",
                    "object_id": obj.id,
                })
                continue
            pred = objects.get(pred_id)
            if pred is None:
                issues.append({
                    "key": key,
                    "type": "Missing",
                    "title": f"{_label(obj)} has a missing predecessor",
                    "detail": "The linked predecessor no longer exists.",
                    "object_id": obj.id,
                })
                continue
            if obj.start_week <= pred.end_week:
                issues.append({
                    "key": key,
                    "type": "Schedule",
                    "title": f"{_label(obj)} starts before {_label(pred)} finishes",
                    "detail": (
                        f"{_label(pred)} ends W{pred.end_week}; "
                        f"{_label(obj)} starts W{obj.start_week}."
                    ),
                    "object_id": obj.id,
                })

    issues.extend(_cycle_issues(objects))
    if ignored:
        for issue in issues:
            issue["ignored"] = issue["key"] in ignored
    return issues


def _cycle_issues(objects: dict) -> list[dict]:
    issues: list[dict] = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {obj_id: WHITE for obj_id in objects}
    reported: set[frozenset] = set()

    def visit(node_id: str, stack: list[str]):
        color[node_id] = GRAY
        stack.append(node_id)
        obj = objects.get(node_id)
        for pred_id in getattr(obj, "predecessors", []) or []:
            if pred_id not in objects:
                continue
            if color[pred_id] == GRAY:
                cycle = stack[stack.index(pred_id):] + [pred_id]
                marker = frozenset(cycle)
                if marker not in reported:
                    reported.add(marker)
                    names = " → ".join(_label(objects[n]) for n in cycle)
                    issues.append({
                        "key": "cycle:" + ":".join(sorted(marker)),
                        "type": "Cycle",
                        "title": "Dependency cycle detected",
                        "detail": names,
                        "object_id": cycle[0],
                    })
            elif color[pred_id] == WHITE:
                visit(pred_id, stack)
        stack.pop()
        color[node_id] = BLACK

    for obj_id in objects:
        if color[obj_id] == WHITE:
            visit(obj_id, [])
    return issues


def issue_summary(issues: list[dict]) -> tuple[int, int]:
    active = [i for i in issues if not i.get("ignored")]
    return len(active), len(issues)

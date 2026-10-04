"""GPA calculation from course percentage scores."""
import re

# (minimum percent, grade points). Edit if your school's scale differs.
SCALE = [(90, 4.0), (80, 3.0), (70, 2.0), (60, 1.0), (0, 0.0)]

# Courses whose names match get +1.0 in the weighted GPA.
WEIGHTED_PATTERN = re.compile(r"^(AP|Honors?|IB|Dual Enrollment)\b", re.I)


def points_for(percent: float) -> float:
    for floor, pts in SCALE:
        if percent >= floor:
            return pts
    return 0.0


def calculate_gpa(courses: list[dict]) -> dict:
    """Each graded course counts as 1 credit. Courses with no score are skipped."""
    unweighted, weighted = [], []
    for c in courses:
        pct = c.get("percent")
        if pct is None:
            continue
        base = points_for(pct)
        bonus = 1.0 if WEIGHTED_PATTERN.match(c.get("course", "")) and base > 0 else 0.0
        c["points"] = base
        c["weighted_points"] = base + bonus
        unweighted.append(base)
        weighted.append(base + bonus)
    if not unweighted:
        return {"gpa_unweighted": None, "gpa_weighted": None, "graded_courses": 0}
    n = len(unweighted)
    return {
        "gpa_unweighted": round(sum(unweighted) / n, 2),
        "gpa_weighted": round(sum(weighted) / n, 2),
        "graded_courses": n,
    }

# Grade scraper

## Deploy on Render
1. Push this folder to a GitHub repo.
2. Render > New > Blueprint > pick the repo (uses render.yaml).
3. PORTAL_BASE is already set to https://az-eef.edupoint.com. Copy the generated SCRAPER_API_KEY.

## GPA
Edit gpa.py to change the grade scale or which course names count as weighted (AP/Honors/IB by default).

## Call from Base44 (backend function)
```js
const res = await fetch("https://YOUR-SERVICE.onrender.com/grades", {
  method: "POST",
  headers: { "Content-Type": "application/json", "x-api-key": Deno.env.get("SCRAPER_API_KEY") },
  body: JSON.stringify({ username, password }),
});
const data = await res.json(); // { semester, gpa, courses: [...] }
```
Store SCRAPER_API_KEY as a Base44 secret. Don't save student passwords in Base44's database.

## Response shape
{ student_name, grading_period (e.g. "Q2P1"), semester (1 or 2), gpa_unweighted, gpa_weighted, graded_courses, courses: [ { period, course, teacher, room, letter, percent, missing, points, weighted_points } ] }

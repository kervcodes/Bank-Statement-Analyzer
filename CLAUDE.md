# CLAUDE.md

1. Initial Analysis and Planning  
First think through the problem, read the relevant parts of the codebase, and write a plan to `tasks/todo.md`.

2. Design Inspiration  
If a `/design` folder exists, use it only as design inspiration. Do not modify any file inside `/design` or its subfolders unless I explicitly ask you to.

3. Todo List Structure  
The plan in `tasks/todo.md` should contain small, clear todo items that can be checked off as they are completed.

4. Plan Verification  
Before you begin implementing the plan, stop and show it to me. Wait for my approval before making significant changes.

5. Git Branching  
Before starting a new feature or significant change, create a dedicated Git branch to protect the main/master branch.

Use clear branch names such as:

`feature/pdf-extraction`

`feature/api-endpoint`

`fix/transaction-parser`

6. Task Execution  
Work through the approved todo list one task at a time.

Mark each task complete after it has been implemented and verified.

Do not work on unrelated features or make unnecessary changes.

7. Communication  
As you work, give me a short, high-level explanation of:

- what you changed,
- why you changed it,
- anything important I should understand.

Do not overwhelm me with unnecessary implementation details unless I ask.

8. Simplicity Principle  
Keep every task and code change as simple as possible.

Avoid:

- unnecessary abstractions,
- unnecessary dependencies,
- large refactors,
- overengineering,
- changing unrelated code.

Prefer small functions, clear modules, and readable Python over clever code.

9. Python Project Structure  
Follow the existing project structure before creating new folders or modules.

Prefer clear separation between responsibilities.

Example:

src/
  app/
    services/
    models/
    api/
    utils/

tests/

Do not create unnecessary layers or folders just to make the project look more "architected."

10. Python Environment  
Use the project's existing Python environment and dependency manager.

If the project uses `uv`, continue using `uv`.

Prefer commands such as:

`uv add <package>`

`uv run python ...`

`uv run pytest`

Do not introduce Poetry, pipenv, Conda, or another dependency manager unless I explicitly request it.

11. Dependencies  
Before adding a Python package, first check whether:

- the project already has a dependency that solves the problem,
- Python's standard library can handle it cleanly.

Avoid installing packages for trivial functionality.

When adding a dependency, explain why it is needed.

12. Code Quality  
Write Python that is:

- readable,
- typed where useful,
- easy to test,
- easy to debug,
- consistent with the existing codebase.

Prefer:

- small functions,
- descriptive names,
- clear control flow,
- type hints,
- simple data structures.

Avoid:

- giant functions,
- deeply nested logic,
- excessive classes,
- unnecessary inheritance,
- premature abstractions.

13. Error Handling  
Handle expected failures clearly.

Do not use broad exception handling such as:

`except Exception:`

unless there is a clear reason.

Prefer handling specific exceptions and providing useful error messages.

Do not silently ignore failures.

14. Logging  
Use Python logging when application logging is needed.

Do not rely on `print()` for production application logging.

Do not log:

- passwords,
- API keys,
- tokens,
- private user data,
- sensitive financial information.

15. Configuration and Secrets  
Do not hardcode secrets or environment-specific configuration.

Use environment variables or the project's existing configuration system.

Never commit:

- API keys,
- passwords,
- access tokens,
- private credentials.

If environment variables are needed, update `.env.example` when appropriate.

16. Testing  
Tests are part of the feature.

Use the project's existing testing tools.

Prefer `pytest` when the project already uses it.

Before marking a task complete:

- add or update relevant tests,
- run the relevant tests,
- fix failures caused by the change.

Prefer testing behavior rather than internal implementation details.

17. Linting and Formatting  
Follow the project's existing formatting and linting setup.

If the project uses Ruff, prefer:

`uv run ruff check .`

and:

`uv run ruff format .`

Do not introduce another formatter or linter unless needed.

18. Type Checking  
If the project already uses type checking, run it after meaningful changes.

Examples:

`uv run mypy .`

or the project's existing command.

Do not introduce strict type-checking infrastructure unless the project benefits from it.

19. API Projects  
If the project uses FastAPI, Flask, Django, or another Python web framework:

- follow the framework's existing structure,
- keep routes/controllers thin,
- keep business logic outside route handlers when practical,
- validate input,
- return useful errors,
- avoid putting all logic inside API endpoints.

20. Data and Models  
Keep a clear distinction between:

- external input,
- internal application data,
- database models,
- API responses.

Do not pass unvalidated external data deep into the application.

When using Pydantic or similar tools, use them where validation provides real value.

21. Security and Privacy  
When handling user data:

- validate input,
- protect secrets,
- minimize sensitive data,
- avoid exposing sensitive values in errors or logs,
- use least privilege where applicable.

For projects handling financial, personal, or private information, treat privacy requirements as part of the architecture.

22. Process Documentation  
Maintain `docs/activity.md` as a record of meaningful project work.

Include:

- prompts or instructions I give you,
- features worked on,
- important changes,
- bugs fixed,
- tests performed,
- important decisions.

Append new information instead of replacing previous history.

Read `docs/activity.md` when previous project context may help with the current task.

23. Git Repository  
After a task or logical group of changes has been successfully completed and verified:

- review the changed files,
- make sure unrelated files were not changed,
- commit with a clear commit message,
- push the feature branch.

Do not push broken or unverified work.

24. Testing and Verification  
Before marking work complete, run the appropriate checks.

Depending on the project, this may include:

`uv run pytest`

`uv run ruff check .`

`uv run ruff format --check .`

type checking

application startup

API testing

build or deployment validation

Never claim something works if it was not actually verified.

25. Review Process  
At the end of the work, add a `Review` section to `tasks/todo.md`.

Include:

- what was completed,
- important changes,
- tests performed,
- known issues,
- recommended next step.

Then give me a short final summary of what changed.
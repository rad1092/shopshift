# Source register

Reviewed 2026-10-08. Public statements below are evidence about a workflow or a
vendor's documented offering, not representative market research or an audit.
No accounts were created, sales contacts made, production data obtained, or
competitor software purchased. All ShopShift fixtures are synthetic.

| ID | Source | What it supports | Limits |
| --- | --- | --- | --- |
| N1 | [Machine-shop scheduling request](https://www.reddit.com/r/manufacturing/comments/1ledswu/scheduling_software/) | A poster explicitly requested visual scheduling, dependencies, and daily Excel uploads while retaining a mandated ERP. | One self-reported need; no verified purchasing intent or market size. |
| N2 | [Production scheduling discussion](https://www.reddit.com/r/manufacturing/comments/1igyxv8/how_do_you_do_your_production_scheduling/) | The original poster reported manual cascading row changes and later selected Monday.com. Other replies described useful spreadsheets. | A process-manufacturing example, not necessarily a machine shop; subjective reports. |
| N3 | [Practical Machinist discussion](https://www.practicalmachinist.com/forum/threads/how-do-you-manage-projects-jobs-for-the-shop.441826/) | A small shop requested machine/operator/routing visibility; replies also favored whiteboards or job racks when time estimates are unreliable. | Mixed experience and promotional replies; not controlled evidence. |
| C1 | [Just Plan It features](https://www.just-plan-it.com/production-scheduling-features) | Finite scheduling, manual adjustment, machine/employee planning, calendars, Excel/API, reports. | Vendor feature description; no trial was run. |
| C2 | [Just Plan It hosting](https://www.just-plan-it.com/security) | Vendor states Azure hosting. | Only hosting architecture used here; security/compliance claims not independently assessed. |
| C3 | [frePPLe editions](https://frepple.com/editions/) | Community finite material/capacity planning, imports, API, scenarios; cloud/enterprise extensions. | Features and edition boundaries can change. |
| C4 | [frePPLe Linux installation](https://frepple.com/docs/current/installation-guide/linux-binaries.html) | 9.19 documentation describes Ubuntu 24 packages, Apache, PostgreSQL and configuration steps. | Not timed or installed here. |
| C5 | [frePPLe Docker installation](https://frepple.com/docs/current/installation-guide/docker-container.html) | Application container and separate PostgreSQL service, including compose guidance. | Local hosting can be offline after setup; not equivalent to mandatory cloud use. |
| C6 | [frePPLe data wizard](https://frepple.com/docs/current/modeling-wizard/index.html) | Guided initial modeling already exists. | Cannot claim competitors lack onboarding. |
| C7 | [frePPLe import documentation](https://frepple.com/docs/current/user-interface/getting-around/importing-data.html) | CSV/XLSX upload, row error reporting, rereadable exports and optional table deletion. | Does not establish whether every ShopShift merge rule is absent or present. |
| C8 | [frePPLe licensing](https://frepple.com/docs/current/license.html) | Community MIT; Enterprise proprietary. | Upstream dependencies have their own licenses. |
| C9 | [MRPeasy production scheduling](https://www.mrpeasy.com/production-scheduling/) | Cloud manufacturing ERP covering scheduling, inventory and execution. | No claim that a customer must migrate every workflow to use it. |
| E1 | [Official OR-Tools job-shop example](https://developers.google.com/optimization/scheduling/job_shop) | Interval-based machine constraints, precedence, makespan objective, known 8-task result. | Educational model, not a complete planner application. |
| E2 | [Pinned source used for execution](https://github.com/google/or-tools/blob/551ad10d94835c99e5e1e684500d3db398c0e345/ortools/sat/samples/minimal_jobshop_sat.py) | Exact upstream source for the executable comparison. | Wrapper only limits resources and captures the returned status. |
| E3 | [CP-SAT solver statuses](https://developers.google.com/optimization/cp/cp_solver) | Integer constraints and distinction between optimal, feasible, infeasible, invalid and unknown. | A returned status is not independent validation of our data/model. |
| L1 | [OR-Tools license](https://github.com/google/or-tools/blob/stable/LICENSE) | Apache-2.0 upstream license. | Distribution must include applicable dependency notices as well. |
| L2 | [Qt for Python licenses](https://doc.qt.io/qtforpython-6/licenses.html) | Qt for Python licensing and component-specific third-party notices. | A package-level label alone is not a bundle license inventory. |
| P1 | [OR-Tools 9.15.6755 metadata](https://pypi.org/pypi/ortools/9.15.6755/json) | Published wheel sizes, dependencies, Python requirement. | Compressed wheel size, not installed application size. |
| P2 | [PySide6-Essentials 6.11.2 metadata](https://pypi.org/pypi/PySide6-Essentials/6.11.2/json) | Published wheels, Python and platform compatibility. | Full PySide6 has additional packages. |
| P3 | [Shiboken6 6.11.2 metadata](https://pypi.org/pypi/shiboken6/6.11.2/json) | Required Qt binding companion. | Platform sizes differ. |
| P4 | [openpyxl 3.1.5 metadata](https://pypi.org/pypi/openpyxl/3.1.5/json) | XLSX reader/writer metadata. | XML hardening and file limits are application responsibilities. |

Reproducible local evidence is in `comparison_ortools.json`,
`comparison_workflow.json` and `comparison_dependencies.json`; generator scripts are in `../scripts/` with
the `comparison_` prefix. Research JSON contains synthetic data or public
package metadata only. It is deliberately small and suitable for version control.

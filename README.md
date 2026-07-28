# Room Advisor

A Home Assistant integration that answers one question:

> Given the sensors and devices available in a room, what actions are advisable
> right now, and why?

Room Advisor observes existing Home Assistant entities, evaluates a set of
built-in rules, and exposes the result as stable, observable entities. It
**never performs the action** — automations, dashboards, notifications and
scripts decide what to do with the advice.

## Why

Advice of this kind is usually built per room, as a pile of template sensors
and helpers. That works until there are eight rooms: the logic drifts, no two
rooms agree, and nothing explains itself when it fires at the wrong moment.

Room Advisor moves that logic into one place with three properties the
template approach lacks:

- **It says why.** Every piece of advice carries a stable reason code and the
  entities it was based on, so a surprising recommendation can be explained
  rather than guessed at.
- **It is honest about missing data.** An input that is unavailable is not
  treated as `false`. Advice to *close* something is allowed on partial
  information; advice to *open* something is not.
- **It does not act.** Nothing is toggled, and no notification is sent. What
  to do with the advice is the consumer's decision, which keeps the
  recommendation testable and the side effects yours.

## Status

**Under construction.** Not yet installable, not usable, and not listed in
HACS. Interfaces will change without migration until the first release.

## Development

Requires Python 3.14 and targets Home Assistant 2026.7.4, which is both the
version CI tests against and the declared minimum.

Home Assistant's test harness cannot run on Windows — `homeassistant.runner`
imports the POSIX-only `fcntl` — so the checks run in a container that matches
the `ubuntu-latest` runner used by CI:

```bash
docker build -f Dockerfile.test -t room-advisor-test .

docker run --rm -v "$PWD:/workspace" room-advisor-test ruff check .
docker run --rm -v "$PWD:/workspace" room-advisor-test ruff format --check .
docker run --rm -v "$PWD:/workspace" room-advisor-test mypy
docker run --rm -v "$PWD:/workspace" room-advisor-test pytest

docker run --rm -v "$PWD:/github/workspace" ghcr.io/home-assistant/hassfest:latest
```

Rebuild the image after changing `requirements-dev.txt`.

Do not create a virtualenv inside the repository. The bind mount and hassfest
both walk the working tree, and a `.venv` containing Home Assistant makes
hassfest try to validate all ~1,400 core integrations.

On Linux or macOS, `pip install -r requirements-dev.txt` in a virtualenv
*outside* the repository works too.

## Licence

MIT. See [LICENSE](LICENSE).


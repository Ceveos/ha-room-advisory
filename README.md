# Room Advisor

A Home Assistant integration that answers one question per room:

> What is worth doing in here right now, and why?

It reads the sensors you already have and publishes the answer as entities.
`sensor.office_window_advice` becomes `open`, with a reason attached saying it
is 4°C cooler outside. Your automations, dashboards and notifications decide
what to do about it.

## Why

The usual way to build this is a template sensor per room. That is fine for one
room. By the eighth you have eight near-copies, they drift apart as you tweak
them one at a time, and when one gives odd advice there is no way to see what it
was reading.

Room Advisor does the job once for every room, and adds three things a template
does not give you:

- **A reason.** Every piece of advice carries a reason code and the entities it
  was based on, so you can check why it fired.
- **Sensible behaviour when a sensor dies.** An unavailable sensor is not read
  as "no". Room Advisor will still tell you to close a window on incomplete
  information, but it will not tell you to open one.
- **No side effects.** It switches nothing and sends nothing. You connect the
  output to whatever you like.


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


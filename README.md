# Room Advisor

A Home Assistant integration that answers one question per room:

> What is worth doing in here right now, and why?

It reads the sensors you already have and publishes the answer as entities.
`sensor.office_window_advice` becomes `open`, with a reason attached saying it
is 4°C cooler outside. Your automations, dashboards and notifications decide
what to do about it.

The point is to write that logic once rather than once per room, and to have
every answer record what it was looking at.

## Status

**Under construction.** Not yet installable, not usable, and not listed in
HACS. Interfaces will change without migration until the first release.

## Development

Requires Python 3.14 and targets Home Assistant 2026.7.4, which is both the
version CI tests against and the declared minimum.

### Running the checks

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

### Running Home Assistant

The checks above never render a screen, so the config flow needs a running
instance to be seen. Open the repository in VS Code and choose *Reopen in
Container*, then run the *Run Home Assistant* task — or `bash scripts/develop`
— and browse to <http://localhost:8123>.

`scripts/develop` writes a throwaway `config/` directory and symlinks the
integration into it, so edits reach the running instance and only need a
restart. Delete `config/` to start again from onboarding.

The generated configuration loads `frontend` rather than `default_config`, and
Home Assistant is started with `--skip-pip`. `default_config` pulls in
bluetooth, cloud, camera and voice, whose optional binary dependencies have no
wheels for this Python; Home Assistant tries to build them on every start, and
a failure part-way through drops the instance into recovery mode with no
frontend. None of them are inputs to Room Advisor.

Home Assistant preloads some of those components regardless of configuration,
so expect around fifteen setup errors at boot for `ffmpeg`, `tts`,
`conversation` and friends. They are inert. Filter the log with
`grep room_advisor` to see only this integration.

The devcontainer installs the same `requirements-dev.txt` as the check image,
so the two cannot drift. It does not replace them: `Dockerfile.test` stays the
fast, pinned gate, and the devcontainer is for looking at the UI.

On Windows, Docker Desktop works, but Home Assistant's own guidance is to run
Docker inside WSL2 and clone the repository there — bind mounts from `D:\` are
noticeably slower.

## Licence

MIT. See [LICENSE](LICENSE).


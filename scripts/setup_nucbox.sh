#!/bin/sh
# Prepare a checked-out Ubuntu host; experiment traffic is a separate command.
set -eu
cd "$(dirname "$0")/.."

if [ "$#" -ne 1 ]; then
    printf '%s\n' 'Usage: sh scripts/setup_nucbox.sh --plan | --install' >&2
    exit 2
fi

case "$1" in
    --plan)
        cat <<'PLAN'
Run --install as your ordinary Linux account on Ubuntu 24.04 LTS.
The installer uses sudo for distribution packages, then creates or refreshes
the repository's .venv and runs the full portable checks. It does not install
an operating system, enable SSH, configure physical NICs, or start a namespace
experiment. Checks use local loopback sockets.

Distribution packages:
  git python3-venv iproute2 iperf3 ethtool iputils-ping tcpdump kmod shellcheck
  cmake g++ libboost-dev clang-format
Python packages:
  requirements-dev.txt and requirements-analysis.txt, installed into .venv
Checks:
  sh scripts/check.sh
  sh scripts/check_analysis.sh
  shellcheck scripts/check.sh scripts/setup_nucbox.sh scripts/check_analysis.sh

Next: inspect_hardware.py, then the authorized nucbox_smoke.py setup check.
PLAN
        exit 0
        ;;
    --install) ;;
    *)
        printf '%s\n' 'Expected --plan or --install.' >&2
        exit 2
        ;;
esac

if [ "$(uname -s)" != Linux ]; then
    printf '%s\n' 'Installation requires Linux; use --plan on the Mac.' >&2
    exit 2
fi
if [ "$(id -u)" -eq 0 ]; then
    printf '%s\n' 'Run as an ordinary account, without sudo before the script.' >&2
    exit 2
fi
python3 - <<'PY'
import platform
import sys
release = platform.freedesktop_os_release()
if (release.get('ID'), release.get('VERSION_ID')) != ('ubuntu', '24.04'):
    sys.exit('Installer supports Ubuntu 24.04 LTS; use the manual guide for other systems.')
if sys.version_info < (3, 12):
    sys.exit('Python 3.12 or newer is required.')
PY

command -v timeout >/dev/null
command -v sudo >/dev/null
sudo -v
timeout 300 sudo -n apt-get update
timeout 300 sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install \
    --yes --no-install-recommends \
    git python3-venv iproute2 iperf3 ethtool iputils-ping tcpdump kmod shellcheck \
    cmake g++ libboost-dev clang-format
sh scripts/setup_environment.sh
sh scripts/check.sh
sh scripts/check_analysis.sh
timeout 120 cmake -S experiments/cpp_network_testing -B build/cpp-network-probe \
    -DPython3_EXECUTABLE="$PWD/.venv/bin/python" -DCMAKE_BUILD_TYPE=Debug
timeout 120 cmake --build build/cpp-network-probe --parallel 2
timeout 45 ctest --test-dir build/cpp-network-probe --output-on-failure
shellcheck scripts/check.sh scripts/setup_nucbox.sh scripts/check_analysis.sh scripts/setup_environment.sh
printf '%s\n' 'Software installed and portable checks passed. Continue with the hardware inspection.'

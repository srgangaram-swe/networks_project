# C++ loopback protocol prototype

Chris Ong's prototype implements a PING/PONG/ACK exchange over TCP. It is
retained alongside the namespace experiment, with its original commit history.
The server reports the time from sending PONG to receiving ACK. This is a
server-side acknowledgment round trip, not the foreground UDP RTT used in
the queue-management comparison.

Build with CMake, a C++17 compiler, Python 3.12+, and Boost headers. On Ubuntu,
install cmake, g++, and libboost-dev. On the Mac, use the existing CMake and
compiler with Boost installed. Build from the project root:

    cmake -S experiments/cpp_network_testing -B build/cpp-network-probe \
      -DCMAKE_BUILD_TYPE=Debug
    cmake --build build/cpp-network-probe --parallel 2
    ctest --test-dir build/cpp-network-probe --output-on-failure

The build enables strict warnings and address/undefined-behavior sanitizers
on GCC or Clang. Tests exercise repeated real exchanges, malformed PING and
ACK frames, refused connections, occupied ports, and exclusive output.
The socket is restricted to 127.0.0.1:5000. A competing listener causes a
failure; the harness never stops another process to obtain that port.

Use the bounded harness rather than launching an unattended server:

    mkdir -p runs
    sh experiments/cpp_network_testing/timing.sh 3 runs/cpp-probe-01

It allows 1 to 100 trials, waits for server readiness, gives each client a
five-second deadline, and retains logs and status in a new output directory.
Cleanup targets only its owned process session. This smoke check is not a
replacement for the paced 512-byte UDP experiment or primary measurements.

//
// Created by Christopher on 10/2/2026.
//

#include <algorithm>
#include <boost/asio.hpp>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>

using boost::asio::ip::tcp;

int main() {
    using std::chrono::duration;
    using std::chrono::steady_clock;

    try {
        boost::asio::io_context io_context;

        tcp::acceptor acceptor(io_context);
        acceptor.open(tcp::v4());
        acceptor.set_option(tcp::acceptor::reuse_address(true));
        acceptor.bind(tcp::endpoint(boost::asio::ip::make_address("127.0.0.1"), 5000));
        acceptor.listen();

        std::cout << "Server waiting for connection on port 5000..." << std::endl;

        tcp::socket socket(io_context);
        acceptor.accept(socket);

        std::cout << "Client connected.\n";

        char buffer[1024] = {};
        std::size_t bytes_received = boost::asio::read(socket, boost::asio::buffer(buffer, 4));

        std::string message(buffer, bytes_received);
        if (message != "PING") {
            throw std::runtime_error("expected a four-byte PING request");
        }

        std::cout << "Received: " << message << '\n';

        std::string response = "PONG";

        std::fill(std::begin(buffer), std::end(buffer), '\0');

        auto t1 = steady_clock::now();

        boost::asio::write(socket, boost::asio::buffer(response));

        bytes_received = boost::asio::read(socket, boost::asio::buffer(buffer, 3));

        auto t2 = steady_clock::now();

        std::cout << "Sent: " << response << '\n';

        message.assign(buffer, bytes_received);
        if (message != "ACK") {
            throw std::runtime_error("expected a three-byte ACK");
        }

        std::cout << "Received: " << message << '\n';

        std::cout << "TCP ping-pong test successful.\n";

        duration<double, std::milli> ms_double = t2 - t1;
        std::cout << std::setprecision(9) << ms_double.count() << "ms\n";

    } catch (const std::exception &e) {
        std::cerr << "Server error: " << e.what() << '\n';
        return 1;
    }

    return 0;
}

//
// Created by Christopher on 10/2/2026.
//

#ifndef NETWORKS_PROJECT_SERVER_HOST_HPP
#define NETWORKS_PROJECT_SERVER_HOST_HPP

#include <boost/asio.hpp>
#include <iostream>
#include <string>
#include <chrono>

using boost::asio::ip::tcp;

int main() {
    using std::chrono::steady_clock;
    using std::chrono::duration;

    try
    {
        boost::asio::io_context io_context;

        tcp::acceptor acceptor(io_context, tcp::endpoint(tcp::v4(), 5000) );

        std::cout << "Server waiting for connection on port 5000...\n";

        tcp::socket socket(io_context);
        acceptor.accept(socket);

        std::cout << "Client connected.\n";

        char buffer[1024] = {};
        std::size_t bytes_received = boost::asio::read(socket, boost::asio::buffer(buffer, 4));

        std::string message(buffer, bytes_received);

        std::cout << "Received: " << message << '\n';

        std::string response = "PONG";

        std::fill(std::begin(buffer), std::end(buffer), '\0');

        auto t1 = steady_clock::now();

        boost::asio::write(socket, boost::asio::buffer(response));

        bytes_received = boost::asio::read(socket, boost::asio::buffer(buffer, 3));

        auto t2 = steady_clock::now();

        std::cout << "Sent: " << response << '\n';

        message.assign(buffer, bytes_received);

        std::cout << "Received: " << message << '\n';

        std::cout << "TCP ping-pong test successful.\n";

        duration<double, std::milli> ms_double = t2 - t1;
        std::cout << ms_double.count() << "ms\n";

    }
    catch (const std::exception& e)
    {
        std::cerr << "Server error: " << e.what() << '\n';
        return 1;
    }

    return 0;
}

#endif //NETWORKS_PROJECT_SERVER_HOST_HPP
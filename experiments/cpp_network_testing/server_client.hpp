//
// Created by Christopher on 10/2/2026.
//

#ifndef NETWORKS_PROJECT_SERVER_CLIENT_HPP
#define NETWORKS_PROJECT_SERVER_CLIENT_HPP

#include <boost/asio.hpp>
#include <iostream>
#include <string>

using boost::asio::ip::tcp;

int main() {
    try
    {
        boost::asio::io_context io_context;

        tcp::socket socket(io_context);

        tcp::endpoint server_endpoint(boost::asio::ip::make_address("127.0.0.1"), 5000);

        std::cout << "Connecting to server...\n";

        socket.connect(server_endpoint);

        std::cout << "Connected.\n";

        std::string message = "PING";

        boost::asio::write(socket, boost::asio::buffer(message));

        std::cout << "Sent: " << message << '\n';

        char buffer[1024] = {};

        std::size_t bytes_received = socket.read_some(boost::asio::buffer(buffer));

        std::string response(buffer, bytes_received);

        std::cout << "Received: " << response << '\n';

        message = "ACK";

        boost::asio::write(socket, boost::asio::buffer(message));

        std::cout << "Sent: " << message << '\n';

        std::cout << "TCP ping-pong test successful.\n";
    }
    catch (const std::exception& e)
    {
        std::cerr << "Client error: " << e.what() << '\n';
        return 1;
    }

    return 0;
}

#endif //NETWORKS_PROJECT_SERVER_CLIENT_HPP

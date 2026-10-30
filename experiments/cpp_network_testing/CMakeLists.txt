cmake_minimum_required(VERSION 3.16)

project(Networks_Project LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Boost REQUIRED COMPONENTS system)
find_package(Threads REQUIRED)

# Server executable
add_executable(server server_host.cpp)
target_link_libraries(server PRIVATE Boost::system Threads::Threads)

# Client executable
add_executable(client server_client.cpp)
target_link_libraries(client PRIVATE Boost::system Threads::Threads)
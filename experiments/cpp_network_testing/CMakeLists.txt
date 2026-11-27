cmake_minimum_required(VERSION 3.16)

project(Networks_Project LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Boost CONFIG REQUIRED)
find_package(Threads REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)

option(ENABLE_SANITIZERS "Enable address and undefined-behavior checks" ON)

# Server executable
add_executable(server server_host.cpp)
target_link_libraries(server PRIVATE Boost::headers Threads::Threads)

# Client executable
add_executable(client server_client.cpp)
target_link_libraries(client PRIVATE Boost::headers Threads::Threads)

foreach(target server client)
    target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror)
    if(ENABLE_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
        target_compile_options(${target} PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(${target} PRIVATE -fsanitize=address,undefined)
    endif()
endforeach()

enable_testing()
add_test(NAME cpp-loopback COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/test_probe.py --build-dir ${CMAKE_BINARY_DIR})
set_tests_properties(cpp-loopback PROPERTIES TIMEOUT 30)

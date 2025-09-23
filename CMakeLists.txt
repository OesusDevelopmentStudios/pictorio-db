cmake_minimum_required(VERSION 3.31.6)

set(CMAKE_BUILD_TYPE Release)

set(CMAKE_CXX_STANDARD 26)

cmake_policy(SET CMP0135 NEW)

set(CMAKE_CXX_FLAGS "-Wall -Wextra -Werror -Wno-unused-result")
set(CMAKE_CXX_FLAGS_RELEASE "-O3")

project(pictorio-db)

add_subdirectory(src)

cmake_minimum_required(VERSION 3.22.1)
project(mish_lab_probe LANGUAGES C CXX)

add_library(mishlabprobe SHARED network_probe.cpp)

find_library(android-lib android)

target_link_libraries(mishlabprobe PRIVATE ${android-lib})

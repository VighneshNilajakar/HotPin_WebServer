# For more information about build system see
# https://docs.espressif.com/projects/esp-idf/en/latest/api-guides/build-system.html
# The following five lines of boilerplate have to be in your project's
# CMakeLists in this exact order for cmake to work correctly
cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(hotpin-firmware)

# Set partition table
set(PROJECT_EXTRA_INCLUDES 
    ${CMAKE_SOURCE_DIR}/main
)

# Use custom partition table
set(PARTITION_TABLE_CSV ${CMAKE_SOURCE_DIR}/partitions.csv)
cmake_minimum_required(VERSION 3.0.2)
project(gazebo_sim_fs150_sitl)

find_package(catkin REQUIRED)
find_package(gazebo REQUIRED)

catkin_package()

add_library(xgc2_fs150_rotor_visual SHARED src/rotor_visual_plugin.cpp)
target_compile_features(xgc2_fs150_rotor_visual PRIVATE cxx_std_17)
target_include_directories(xgc2_fs150_rotor_visual PRIVATE ${GAZEBO_INCLUDE_DIRS})
target_link_libraries(xgc2_fs150_rotor_visual PRIVATE ${GAZEBO_LIBRARIES})
install(TARGETS xgc2_fs150_rotor_visual LIBRARY DESTINATION ${CATKIN_PACKAGE_LIB_DESTINATION})

catkin_install_python(PROGRAMS
  scripts/prepare_fs150_robot
  scripts/generate_fs150_sitl_params.py
  scripts/generate_fs150_urdf.py
  scripts/start_sitl.py
  scripts/start_mavros.py
  scripts/render_fs150_indoor_sdf.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY config docs firmware launch models reports urdf
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
  USE_SOURCE_PERMISSIONS
)

install(DIRECTORY scripts
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
  USE_SOURCE_PERMISSIONS
  PATTERN "__pycache__" EXCLUDE
  PATTERN "*.pyc" EXCLUDE
)

if(CATKIN_ENABLE_TESTING)
  add_executable(fs150_rotor_visual_pose_test test/test_rotor_visual_pose.cpp)
  target_compile_features(fs150_rotor_visual_pose_test PRIVATE cxx_std_17)
  target_include_directories(fs150_rotor_visual_pose_test PRIVATE src ${GAZEBO_INCLUDE_DIRS})
  target_link_libraries(fs150_rotor_visual_pose_test PRIVATE ${GAZEBO_LIBRARIES})
  add_test(NAME fs150_rotor_visual_pose COMMAND fs150_rotor_visual_pose_test)
  find_package(roslaunch REQUIRED)
  find_package(PythonInterp REQUIRED)
  add_test(NAME fs150sitl_parallel_launch
    COMMAND ${PYTHON_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/test/test_parallel_launch.py)
  add_test(NAME fs150_shared_visual_assets
    COMMAND ${PYTHON_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/test/test_visual_assets.py)
  add_test(NAME fs150_camera_assets
    COMMAND ${PYTHON_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/test/test_camera_assets.py)
  add_test(NAME fs150_model_plugins
    COMMAND ${PYTHON_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/test/test_model_plugins.py)
  add_test(NAME fs150_render_cache
    COMMAND ${PYTHON_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/test/test_render_cache.py)
  add_test(NAME fs150_mavros_start_order
    COMMAND ${PYTHON_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/test/test_mavros_start_order.py)
  roslaunch_add_file_check(launch/fs150.launch)
endif()

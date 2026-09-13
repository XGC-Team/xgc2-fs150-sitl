cmake_minimum_required(VERSION 3.0.2)
project(gazebo_sim_fs150_sitl)

find_package(catkin REQUIRED)

catkin_package()

catkin_install_python(PROGRAMS
  scripts/generate_fs150_sitl_params.py
  scripts/generate_fs150_urdf.py
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
  find_package(roslaunch REQUIRED)
  find_package(PythonInterp REQUIRED)
  add_test(NAME fs150_shared_visual_assets
    COMMAND ${PYTHON_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/test/test_visual_assets.py)
  add_test(NAME fs150_camera_assets
    COMMAND ${PYTHON_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/test/test_camera_assets.py)
  roslaunch_add_file_check(launch/fs150.launch)
endif()

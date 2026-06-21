cmake_minimum_required(VERSION 3.0.2)
project(gazebo_sim_fs150_sitl)

find_package(catkin REQUIRED COMPONENTS roslaunch)

catkin_package()

catkin_install_python(PROGRAMS
  scripts/generate_fs150_sitl_params.py
  scripts/render_fs150_indoor_sdf.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY config launch models reports
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)

if(CATKIN_ENABLE_TESTING)
  roslaunch_add_file_check(launch/fs150.launch)
endif()

#include "rotor_visual_pose.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>

int main() {
  using namespace ignition::math;
  const Pose3d photo(.045, -.0536190265, .023, 0, 0, 0);
  xgc2_fs150::RotorVisualPose rotation(photo);
  Pose3d output;
  for (double angle : {0., .4, -.7, 2.5}) {
    // The equivalent dynamics axis differs from the photo axis. Neither body
    // tilt nor world translation may orbit the appearance around that axis.
    const Pose3d base(7, -2, 1, .3, -.2, 1.1);
    const Pose3d physical(.13, -.22, .023, 0, 0, angle);
    const Pose3d rotor(base.Pos() + base.Rot().RotateVector(physical.Pos()),
                       base.Rot() * physical.Rot());
    if (!rotation.Update(base, rotor, output) ||
        !output.Pos().Equal(photo.Pos(), 1e-12) ||
        !output.Rot().Equal(Quaterniond(0, 0, angle), 1e-12) ||
        rotation.Update(base, rotor, output))
      throw std::runtime_error("photo axis, measured rotor angle or unchanged-frame cache differs");
    const Pose3d moved(-4, 5, 2, -.4, .1, -.6);
    const Pose3d moved_rotor(moved.Pos() + moved.Rot().RotateVector(physical.Pos()),
                             moved.Rot() * physical.Rot());
    if (rotation.Update(moved, moved_rotor, output))
      throw std::runtime_error("base movement changed relative rotor angle");
  }
  std::cout << "Measured rotor angles preserved; photo axis fixed; unchanged frames skipped\n";
}

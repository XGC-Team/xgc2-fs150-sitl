#pragma once
#include <ignition/math/Pose3.hh>

namespace xgc2_fs150 {
// Physical link positions are deliberately unused: the photo rotor has its own
// axis centre. Only its orientation follows the real rotor relative to base.
class RotorVisualPose {
 public:
  explicit RotorVisualPose(const ignition::math::Pose3d& rest) : rest_(rest) {}
  bool Update(const ignition::math::Pose3d& base_world,
              const ignition::math::Pose3d& rotor_world,
              ignition::math::Pose3d& output) {
    const auto relative = base_world.Rot().Inverse() * rotor_world.Rot();
    if (seen_ && relative.Equal(previous_, 1e-12)) return false;
    previous_ = relative;
    seen_ = true;
    output = {rest_.Pos(), relative * rest_.Rot()};
    return true;
  }
 private:
  ignition::math::Pose3d rest_;
  ignition::math::Quaterniond previous_;
  bool seen_ = false;
};
}  // namespace xgc2_fs150

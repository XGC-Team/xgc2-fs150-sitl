#include "rotor_visual_pose.hpp"
#include <gazebo/common/Events.hh>
#include <gazebo/common/Plugin.hh>
#include <gazebo/rendering/Scene.hh>
#include <gazebo/rendering/Visual.hh>
#include <memory>
#include <string>

namespace xgc2_fs150 {
class RotorVisualPlugin : public gazebo::VisualPlugin {
  struct State {
    std::weak_ptr<gazebo::rendering::Visual> target, base, rotor;
    RotorVisualPose pose;
    explicit State(const ignition::math::Pose3d& rest) : pose(rest) {}
    void Update() {
      auto appearance = target.lock();
      auto body = base.lock();
      auto source = rotor.lock();
      if (!appearance || !body || !source) return;
      ignition::math::Pose3d next;
      if (pose.Update(body->WorldPose(), source->WorldPose(), next))
        appearance->SetPose(next);
    }
  };
 public:
  ~RotorVisualPlugin() override { connection_.reset(); state_.reset(); }
  void Load(gazebo::rendering::VisualPtr visual, sdf::ElementPtr sdf) override {
    auto base = visual->GetParent();
    if (!base || !base->GetParent() || !sdf->HasElement("rotor_link")) return;
    // Gazebo creates link render nodes before loading their mesh visuals,
    // including links without meshes. Resolve once; never scan each frame.
    const auto name = base->GetParent()->Name() + "::" + sdf->Get<std::string>("rotor_link");
    auto rotor = base->GetScene()->GetVisual(name);
    if (!rotor) {
      gzerr << "FS150 rotor visual source link missing: " << name << "\n";
      return;
    }
    state_ = std::make_shared<State>(visual->Pose());
    state_->target = visual;
    state_->base = base;
    state_->rotor = rotor;
    const std::weak_ptr<State> weak = state_;
    connection_ = gazebo::event::Events::ConnectPreRender([weak] {
      if (auto state = weak.lock()) state->Update();
    });
  }
 private:
  std::shared_ptr<State> state_;
  gazebo::event::ConnectionPtr connection_;
};
GZ_REGISTER_VISUAL_PLUGIN(RotorVisualPlugin)
}  // namespace xgc2_fs150

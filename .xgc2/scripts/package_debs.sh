#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT=""
OUTPUT_DIR=""
ROS_DISTRO="${ROS_DISTRO:-noetic}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

product_version() {
  awk -F': *' '/^version:[[:space:]]*/ {print $2; exit}' "${REPO_ROOT}/.xgc2/product.yml"
}

VERSION="${PACKAGE_VERSION:-$(product_version)}"
PACKAGE="ros-${ROS_DISTRO}-xgc2-gazebo-sim-fs150-sitl"
ROS_PACKAGE="gazebo_sim_fs150_sitl"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-root)
      INSTALL_ROOT="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${INSTALL_ROOT}" || -z "${OUTPUT_DIR}" ]]; then
  echo "--install-root and --output-dir are required" >&2
  exit 1
fi

if [[ -z "${VERSION}" ]]; then
  echo "package version is missing" >&2
  exit 1
fi

ARCH="$(dpkg --print-architecture)"
PREFIX="/opt/ros/${ROS_DISTRO}"
PREFIX_ROOT="${INSTALL_ROOT}${PREFIX}"
BUILD_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${BUILD_DIR}"
}
trap cleanup EXIT

mkdir -p "${OUTPUT_DIR}"
rm -f "${OUTPUT_DIR}"/*.deb

copy_path() {
  local src="$1"
  local dst_root="$2"
  if [[ -e "${src}" ]]; then
    mkdir -p "${dst_root}$(dirname "${src#${INSTALL_ROOT}}")"
    cp -a "${src}" "${dst_root}${src#${INSTALL_ROOT}}"
  fi
}

pkg_root="${BUILD_DIR}/${PACKAGE}"
mkdir -p "${pkg_root}"

copy_path "${PREFIX_ROOT}/share/${ROS_PACKAGE}" "${pkg_root}"
copy_path "${PREFIX_ROOT}/lib/${ROS_PACKAGE}" "${pkg_root}"
copy_path "${INSTALL_ROOT}/usr/share/xgc2/process-definitions/xgc2-gazebo-sim-fs150-sitl.json" "${pkg_root}"

mkdir -p "${pkg_root}/DEBIAN" "${pkg_root}/usr/share/doc/${PACKAGE}"
cat > "${pkg_root}/DEBIAN/control" <<EOF
Package: ${PACKAGE}
Version: ${VERSION}
Section: misc
Priority: optional
Architecture: ${ARCH}
Maintainer: XGC2 <apt@example.com>
Depends: python3, ros-${ROS_DISTRO}-roslaunch, ros-${ROS_DISTRO}-mavros, ros-${ROS_DISTRO}-xgc2-gazebo-sim-px4-1-12 (>= 1.12.3-16)
Description: FS150 PX4 1.12 iris SITL wrapper with package-owned Gazebo meshes and RViz URDF
EOF
printf 'xgc2-gazebo-sim-fs150-sitl package\n' > "${pkg_root}/usr/share/doc/${PACKAGE}/README"
chmod 0755 "${pkg_root}/DEBIAN"

fakeroot dpkg-deb --build "${pkg_root}" "${OUTPUT_DIR}/${PACKAGE}_${VERSION}_${ARCH}.deb" >/dev/null
find "${OUTPUT_DIR}" -maxdepth 1 -type f -name '*.deb' -print | sort

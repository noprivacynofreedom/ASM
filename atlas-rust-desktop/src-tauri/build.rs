fn main() {
    // main.rs reads this with option_env!: rebuild when build-release.ps1 sets another data folder.
    println!("cargo:rerun-if-env-changed=ATLAS_BUILD_DATA_ROOT");
    tauri_build::build()
}

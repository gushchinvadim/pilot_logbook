// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "SIMTrainingCore", platforms: [.macOS(.v13), .iOS(.v17)],
    products: [.library(name: "SIMTrainingCore", targets: ["SIMTrainingCore"])],
    targets: [.target(name: "SIMTrainingCore", path: "SIMTraining/Sources/Core"),
              .testTarget(name: "SIMTrainingCoreTests", dependencies: ["SIMTrainingCore"], path: "Tests/SIMTrainingCoreTests")])

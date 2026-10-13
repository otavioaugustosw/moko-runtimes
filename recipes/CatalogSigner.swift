import CryptoKit
import Darwin
import Foundation

enum CatalogSigner {
    static func run(_ arguments: [String]) throws {
        guard let command = arguments.first, arguments.count == (command == "generate" ? 3 : 4) else {
            throw Failure("usage: CatalogSigner generate PRIVATE PUBLIC | sign PRIVATE CATALOG SIGNATURE")
        }
        let mode = arguments[0], privateURL = URL(fileURLWithPath: arguments[1])
        let key: Curve25519.Signing.PrivateKey
        if mode == "generate" && !FileManager.default.fileExists(atPath: privateURL.path) {
            key = Curve25519.Signing.PrivateKey()
            let descriptor = open(privateURL.path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0o600)
            guard descriptor >= 0 else { throw Failure("could not create the private catalog key") }
            let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
            defer { try? file.close() }
            try file.write(contentsOf: key.rawRepresentation)
            try file.synchronize()
        } else {
            key = try Curve25519.Signing.PrivateKey(rawRepresentation: Data(contentsOf: privateURL))
        }
        if mode == "generate" {
            try Data((key.publicKey.rawRepresentation.base64EncodedString() + "\n").utf8)
                .write(to: URL(fileURLWithPath: arguments[2]), options: .atomic)
            print("catalog key prepared; private material was not printed")
        } else if mode == "sign" {
            let payload = try Data(contentsOf: URL(fileURLWithPath: arguments[2]))
            guard payload.count <= 1_000_000, (try JSONSerialization.jsonObject(with: payload)) is [String: Any] else {
                throw Failure("catalog must be a JSON object no larger than 1 mb")
            }
            let signature = try key.signature(for: payload)
            guard key.publicKey.isValidSignature(signature, for: payload) else {
                throw Failure("signature self-check failed")
            }
            try signature.write(to: URL(fileURLWithPath: arguments[3]), options: .atomic)
            print("catalog signed with ed25519 and verified")
        } else {
            throw Failure("unknown catalog signer command")
        }
    }
    struct Failure: LocalizedError {
        let message: String
        init(_ message: String) { self.message = message }
        var errorDescription: String? { message }
    }
}

do { try CatalogSigner.run(Array(CommandLine.arguments.dropFirst())) } catch {
    FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8))
    exit(1)
}

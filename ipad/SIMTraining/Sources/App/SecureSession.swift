import Foundation
import Security

enum SecureSession {
    private static let service = "ru.gvedynamics.simtraining.session"
    private static var query: [String: Any] { [kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: service, kSecAttrAccount as String: "last-instructor"] }
    static func load() throws -> Credentials? {
        var request = query; request[kSecReturnData as String] = true; request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw APIError.message("Не удалось открыть сохранённый вход в Keychain.") }
        return try Wire.decoder().decode(Credentials.self, from: data)
    }
    static func save(_ credentials: Credentials) throws {
        let data = try Wire.encoder().encode(credentials)
        let status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var item = query; item[kSecValueData as String] = data
            item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { throw APIError.message("Не удалось сохранить вход в Keychain.") }
        } else if status != errSecSuccess { throw APIError.message("Не удалось обновить вход в Keychain.") }
    }
    static func clear() { SecItemDelete(query as CFDictionary) }
}

import Foundation

struct Credentials: Codable {
    let server: String
    let token: String
    let profile: Profile
}
enum APIError: LocalizedError {
    case invalidServer, unauthorized, message(String), noResponse
    var errorDescription: String? {
        switch self {
        case .invalidServer: return "Укажите адрес рабочего сервера SIM Training по HTTPS."
        case .unauthorized: return "Сервер требует повторного входа. Черновики остались на iPad."
        case .message(let text): return text
        case .noResponse: return "Не удалось связаться с сервером. Загруженные задания и черновики доступны на iPad."
        }
    }
}
final class NoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
@MainActor final class SIMAPI {
    let server: URL
    var token: String?
    private let session: URLSession
    init(server: String, token: String? = nil) throws {
        guard let url = URL(string: server.trimmingCharacters(in: .whitespacesAndNewlines)),
              let host = url.host, url.user == nil, url.password == nil, url.query == nil,
              url.fragment == nil, url.path.isEmpty || url.path == "/" else { throw APIError.invalidServer }
        var valid = url.scheme == "https" && host == "type-rating.survey-ebt.ru"
        #if DEBUG
        if url.scheme == "http" && (host == "localhost" || host == "127.0.0.1" || host.hasPrefix("192.168.") || host.hasPrefix("10.")) { valid = true }
        #endif
        guard valid else { throw APIError.invalidServer }
        self.server = url; self.token = token
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 20
        configuration.timeoutIntervalForResource = 60
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.httpCookieAcceptPolicy = .never
        configuration.httpShouldSetCookies = false
        session = URLSession(configuration: configuration, delegate: NoRedirect(), delegateQueue: nil)
    }
    var normalizedServer: String { server.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) }
    func request<T: Decodable>(_ path: String, method: String = "GET", body: Data? = nil) async throws -> T {
        guard path.hasPrefix("/api/"), let url = URL(string: path, relativeTo: server)?.absoluteURL,
              url.host == server.host, url.scheme == server.scheme, url.port == server.port else { throw APIError.invalidServer }
        var request = URLRequest(url: url); request.httpMethod = method; request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token { request.setValue("Token " + token, forHTTPHeaderField: "Authorization") }
        let data: Data, response: URLResponse
        do { (data, response) = try await session.data(for: request) }
        catch { throw APIError.noResponse }
        guard let http = response as? HTTPURLResponse else { throw APIError.noResponse }
        if http.statusCode == 401 { throw HTTPFailure(status: 401, message: APIError.unauthorized.localizedDescription) }
        guard (200...299).contains(http.statusCode) else {
            if path == "/api/api-token-auth/" && http.statusCode == 400 {
                throw HTTPFailure(status: 400, message: "Не удалось выполнить вход. Проверьте логин и пароль SIM Training.")
            }
            let message = HTTPFailure.responseMessage(data) ?? "Сервер отклонил запрос. Черновик сохранён."
            throw HTTPFailure(status: http.statusCode, message: message)
        }
        do { return try Wire.decoder().decode(T.self, from: data) }
        catch { throw APIError.message("Не удалось прочитать ответ сервера. Черновик сохранён.") }
    }
    func login(username: String, password: String) async throws -> Profile {
        struct Token: Decodable { let token: String }
        let body = try JSONSerialization.data(withJSONObject: ["username": username, "password": password])
        let result: Token = try await request("/api/api-token-auth/", method: "POST", body: body)
        token = result.token
        let profile: Profile = try await request("/api/auth/me/")
        guard profile.isInstructor else { token = nil; throw APIError.message("В первой версии приложения доступно рабочее место инструктора. У этой учётной записи нет профиля инструктора.") }
        return profile
    }
}

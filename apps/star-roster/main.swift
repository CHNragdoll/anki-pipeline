import Darwin
import Foundation
import SwiftUI

if CommandLine.arguments.dropFirst().first == "--verify" {
    Task {
        do {
            let roster = try await Archive().load()
            let events = roster.events
            let previousAt = Date(timeIntervalSince1970: 100)
            let detectedAt = Date(timeIntervalSince1970: 200)
            let kept = Star(id: 1, login: "fixture-one", starredAt: .init(timeIntervalSince1970: 60))
            let removed = Star(id: 2, login: "fixture-two", starredAt: .init(timeIntervalSince1970: 50))
            let added = Star(id: 3, login: "fixture-three", starredAt: .init(timeIntervalSince1970: 120))
            let fixture = Roster(snapshots: [
                Snapshot(collectedAt: previousAt, users: [removed, kept], changes: nil),
                Snapshot(collectedAt: detectedAt, users: [kept, added],
                         changes: .init(previousAt: previousAt, added: [added], removed: [removed])),
            ], unavailable: 0, nonComparable: 0)
            precondition(fixture.events.map(\.star.id) == [2, 3, 1, 2])
            precondition(fixture.events.first?.exactTime == nil && fixture.events.first?.time == detectedAt)
            precondition(fixture.events.filter(\.baseline).count == 2)
            precondition(fixture.members.map(\.id) == [3, 1])
            precondition(zip(events, events.dropFirst()).allSatisfy { $0.time >= $1.time })
            precondition(events.filter { !$0.added }.allSatisfy { $0.exactTime == nil && $0.time > $0.previousAt })
            precondition(Set(roster.members.map(\.id)).count == roster.members.count)
            print("snapshots=\(roster.snapshots.count) unavailable=\(roster.unavailable) incomplete=\(roster.nonComparable) members=\(roster.members.count) historical=\(events.filter(\.baseline).count) added=\(events.filter { $0.added && !$0.baseline }.count) removed=\(events.filter { !$0.added }.count)")
            print("firstSnapshot=\(roster.snapshots.first?.collectedAt.ISO8601Format() ?? "unknown") oldestEvent=\(events.last?.time.ISO8601Format() ?? "unknown")")
            print("latest=\(roster.latest?.collectedAt.ISO8601Format() ?? "unknown")")
            exit(EXIT_SUCCESS)
        } catch {
            print("Verification failed: \(error)")
            exit(EXIT_FAILURE)
        }
    }
    dispatchMain()
} else {
    StarApp.main()
}

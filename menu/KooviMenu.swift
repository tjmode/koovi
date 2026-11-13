// KooviMenu - the Koovi icon in the menu bar.
//
// Shows Koovi's main switches and flips them. It never decides anything and never writes the
// settings file itself: it reads `koovi settings --json` and changes things with `koovi set`,
// through the shim at ~/.koovi/bin/koovi, so koovi.py stays the only brain. It wakes only when
// the settings file changes or you open the menu. One copy runs at a time. It quits by itself
// when Koovi is updated (the next hook starts the new one), removed, or hidden.
//
// Build:  xcrun swiftc -O -o koovi-menu KooviMenu.swift
// Run:    koovi-menu ~/.koovi/bin/koovi 1.0.0
// Checks: koovi-menu SHIM VERSION --peek 3    open the menu for 3 seconds, then quit
//         koovi-menu SHIM VERSION --selftest  print the menu, press every item once, quit (use a fake shim)

import AppKit

let args = CommandLine.arguments
let shim = args.count > 1 ? args[1] : NSHomeDirectory() + "/.koovi/bin/koovi"
let myVersion = args.count > 2 ? args[2] : ""
let selftest = args.contains("--selftest")
let peekSeconds: Double? = args.firstIndex(of: "--peek").flatMap { $0 + 1 < args.count ? Double(args[$0 + 1]) : nil }

// one copy at a time; the pid and version inside let koovi.py find and replace this copy
let lockFd: Int32 = {
    if selftest { return -1 }
    // the shim lives in ~/.koovi/bin, so the lock sits in ~/.koovi, where koovi.py looks for it
    let dir = ((shim as NSString).deletingLastPathComponent as NSString).deletingLastPathComponent
    let fd = open(dir + "/menu.lock", O_CREAT | O_RDWR, 0o644)
    if fd < 0 || flock(fd, LOCK_EX | LOCK_NB) != 0 { exit(0) }
    ftruncate(fd, 0)
    let note = "\(getpid()) \(myVersion)\n"
    _ = note.withCString { write(fd, $0, strlen($0)) }
    return fd
}()

// Diagnostics: a menu stopped by SIGTERM says who sent it (koovi.py copies this into the diary).
// Nothing in the handler allocates: the words are laid out once, the pid is written in place.
let termHead = Array("koovi-menu: stopped by SIGTERM from pid ".utf8)
let termHeadCount = termHead.count
let termBuf: UnsafeMutablePointer<UInt8> = {
    let b = UnsafeMutablePointer<UInt8>.allocate(capacity: termHead.count + 24)
    for (i, c) in termHead.enumerated() { b[i] = c }
    return b
}()
var termAction: sigaction = {
    var sa = sigaction()
    sa.sa_flags = SA_SIGINFO
    sa.__sigaction_u.__sa_sigaction = { _, info, _ in
        var n = Int(info?.pointee.si_pid ?? 0)
        var digits = 0
        var m = n
        repeat { digits += 1; m /= 10 } while m > 0
        var i = termHeadCount + digits - 1
        repeat { termBuf[i] = UInt8(48 + n % 10); n /= 10; i -= 1 } while n > 0
        termBuf[termHeadCount + digits] = 10
        _ = write(2, termBuf, termHeadCount + digits + 1)
        _exit(143)
    }
    return sa
}()
_ = sigaction(SIGTERM, &termAction, nil)

/// Run a Koovi command through the shim. Returns its exit code and what it printed.
func koovi(_ words: [String]) -> (Int32, String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: shim)
    p.arguments = words
    let out = Pipe()
    p.standardOutput = out
    p.standardError = FileHandle.nullDevice
    do { try p.run() } catch { return (-1, "") }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return (p.terminationStatus, String(decoding: data, as: UTF8.self))
}

func openFile(_ path: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    p.arguments = ["-t", path]
    try? p.run()
}

let modes: [(key: String, title: String, hint: String)] = [
    ("voice", "Voice", "Speaks out loud when a session needs you"),
    ("quiet", "Screen light", "A coloured frame flashes, no sound"),
    ("auto", "Auto", "Speaks on headphones, flashes on speakers"),
]
let quietPresets: [(start: String, end: String)] = [("22:00", "07:00"), ("23:00", "08:00")]

final class KooviMenu: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var status: NSStatusItem?
    let menu = NSMenu()
    var snap: [String: Any] = [:]
    var refreshing = false
    var openTimer: Timer?
    var watcher: DispatchSourceFileSystemObject?
    var configStamp: Date?
    var lastNote = ""

    let header = NSMenuItem()
    let onItem = NSMenuItem()
    let modeTitle = NSMenuItem()
    var modeItems: [NSMenuItem] = []
    let modeHint = NSMenuItem()
    let callsItem = NSMenuItem()
    let micLine = NSMenuItem()
    let agentsItem = NSMenuItem()
    let quietItem = NSMenuItem()
    let mutedItem = NSMenuItem()
    let testItem = NSMenuItem()
    let lastLine = NSMenuItem()
    let settingsItem = NSMenuItem()
    let diaryItem = NSMenuItem()
    let loginItem = NSMenuItem()
    let hideItem = NSMenuItem()

    func item(_ it: NSMenuItem, _ title: String, _ action: Selector?) -> NSMenuItem {
        it.title = title
        it.target = self
        it.action = action
        return it
    }

    func note(_ it: NSMenuItem, indent: Bool = false) -> NSMenuItem {
        it.isEnabled = false
        it.indentationLevel = indent ? 1 : 0
        return it
    }

    func build() {
        menu.autoenablesItems = false
        menu.delegate = self
        menu.addItem(note(header))
        menu.addItem(item(onItem, "Koovi on", #selector(toggleOn)))
        menu.addItem(.separator())
        menu.addItem(note(item(modeTitle, "How it reaches you", nil)))
        for m in modes {
            let it = item(NSMenuItem(), m.title, #selector(pickMode(_:)))
            it.representedObject = m.key
            it.indentationLevel = 1
            modeItems.append(it)
            menu.addItem(it)
        }
        menu.addItem(note(modeHint, indent: true))
        menu.addItem(.separator())
        menu.addItem(item(callsItem, "Stay quiet during calls", #selector(toggleCalls)))
        menu.addItem(note(micLine, indent: true))
        menu.addItem(item(agentsItem, "Wait for research to finish", #selector(toggleAgents)))
        menu.addItem(item(quietItem, "Quiet hours", nil))
        quietItem.submenu = NSMenu()
        menu.addItem(item(mutedItem, "Muted projects", nil))
        mutedItem.submenu = NSMenu()
        menu.addItem(.separator())
        menu.addItem(item(testItem, "Test voice", #selector(testVoice)))
        menu.addItem(note(lastLine, indent: true))
        menu.addItem(.separator())
        menu.addItem(item(settingsItem, "All settings…", #selector(openSettings)))
        menu.addItem(item(diaryItem, "What did Koovi do?", #selector(openDiary)))
        menu.addItem(item(loginItem, "Start at login", #selector(toggleLogin)))
        menu.addItem(item(hideItem, "Hide from menu bar", #selector(hide)))
        // macOS 26 gives "…settings…" a gear by itself; the rest of the group gets one too, so it lines up
        for (it, symbol) in [(testItem, "play"), (settingsItem, "gearshape"), (diaryItem, "list.bullet.rectangle"),
                             (loginItem, "power"), (hideItem, "eye.slash")] {
            it.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)
        }
    }

    // ------------------------------------------------------------------ reading

    func flag(_ key: String, _ fallback: Bool = true) -> Bool { snap[key] as? Bool ?? fallback }
    func text(_ key: String) -> String? { snap[key] as? String }
    var configPath: String { text("config_path") ?? NSHomeDirectory() + "/.koovi/config.yaml" }

    func refresh() {
        if refreshing { return }
        refreshing = true
        DispatchQueue.global(qos: .userInitiated).async {
            let (_, out) = koovi(["settings", "--json"])
            let got = (try? JSONSerialization.jsonObject(with: Data(out.utf8))) as? [String: Any]
            DispatchQueue.main.async { self.refreshing = false; self.take(got) }
        }
    }

    func take(_ got: [String: Any]?) {
        guard let got = got else {
            if !selftest { NSApp.terminate(nil) }  // Koovi is gone; a hook brings a new menu if it comes back
            return
        }
        if !selftest {
            if let v = got["version"] as? String, !myVersion.isEmpty, v != myVersion { NSApp.terminate(nil) }
            if got["menu_bar"] as? Bool == false { NSApp.terminate(nil) }
        }
        snap = got
        render()
        if watcher == nil { watchSettings() }
    }

    /// Wake only when something in ~/.koovi is replaced, and refresh only when that was the settings file.
    func watchSettings() {
        let dir = (configPath as NSString).deletingLastPathComponent
        let fd = open(dir, O_EVTONLY)
        if fd < 0 { return }
        let src = DispatchSource.makeFileSystemObjectSource(fileDescriptor: fd, eventMask: .write, queue: .main)
        src.setEventHandler { [weak self] in self?.settingsMaybeChanged() }
        src.setCancelHandler { close(fd) }
        src.resume()
        watcher = src
        configStamp = stamp()
    }

    func stamp() -> Date? {
        (try? FileManager.default.attributesOfItem(atPath: configPath))?[.modificationDate] as? Date
    }

    func settingsMaybeChanged() {
        let now = stamp()
        if now != configStamp { configStamp = now; refresh() }
    }

    // ------------------------------------------------------------------ drawing

    func setIcon(on: Bool) {
        guard let button = status?.button else { return }
        let names = on ? ["waveform"] : ["waveform.slash", "speaker.slash"]
        let image = names.lazy.compactMap {
            NSImage(systemSymbolName: $0, accessibilityDescription: on ? "Koovi" : "Koovi is off")
        }.first
        image?.isTemplate = true
        button.image = image
        button.title = image == nil ? "K" : ""
        button.toolTip = on ? "Koovi" : "Koovi is off"
    }

    func bold(_ s: String) -> NSAttributedString {
        NSAttributedString(string: s, attributes: [.font: NSFont.menuFont(ofSize: 0).bold])
    }

    func render() {
        let error = text("error") ?? ""
        let on = flag("enabled")
        let mode = text("mode") ?? "voice"
        setIcon(on: on && error.isEmpty)
        let switches = [onItem, callsItem, agentsItem, quietItem, mutedItem, testItem] + modeItems
        if !error.isEmpty {
            header.attributedTitle = bold("Koovi settings file has an error")
            modeHint.title = error
            switches.forEach { $0.isEnabled = false }
            return
        }
        switches.forEach { $0.isEnabled = true }
        let say = modes.first { $0.key == mode }
        header.attributedTitle = bold(on ? "Koovi is on · " + (say?.title.lowercased() ?? mode) : "Koovi is off · silent everywhere")
        onItem.state = on ? .on : .off
        for it in modeItems {
            it.state = (it.representedObject as? String) == mode ? .on : .off
            it.isEnabled = on
        }
        modeHint.title = say?.hint ?? ""
        modeTitle.isEnabled = false

        let calls = flag("wait_for_mic")
        callsItem.state = calls ? .on : .off
        callsItem.isEnabled = on
        if !calls {
            micLine.title = "Koovi may talk over your calls"
        } else if let who = text("mic_name") {
            micLine.title = who.isEmpty ? "Right now: nothing is using the mic" : "Right now: \(who) is using the mic"
        } else {
            micLine.title = "Right now: cannot tell"
        }
        agentsItem.state = flag("wait_for_agents") ? .on : .off
        agentsItem.isEnabled = on

        renderQuietHours()
        renderMuted()
        if !lastNote.isEmpty {
            lastLine.title = lastNote
        } else if let last = snap["last_said"] as? [String: Any], let line = last["line"] as? String {
            let at = (last["at"] as? String).map { " at " + String($0.suffix(8).prefix(5)) } ?? ""
            lastLine.title = "Last\(at): \(line)"
        } else {
            lastLine.title = "Nothing said yet"
        }
        loginItem.state = flag("login", false) ? .on : .off
    }

    func renderQuietHours() {
        let q = snap["quiet_hours"] as? [String: Any] ?? [:]
        let start = q["start"] as? String, end = q["end"] as? String
        let sub = quietItem.submenu!
        sub.removeAllItems()
        sub.autoenablesItems = false
        let off = item(NSMenuItem(), "Off", #selector(pickQuiet(_:)))
        off.state = (start == nil || end == nil) ? .on : .off
        sub.addItem(off)
        var presets = quietPresets
        if let s = start, let e = end, !presets.contains(where: { $0 == (s, e) }) { presets.append((s, e)) }
        for p in presets {
            let it = item(NSMenuItem(), "\(p.start) to \(p.end)", #selector(pickQuiet(_:)))
            it.representedObject = [p.start, p.end]
            it.state = (start, end) == (p.start, p.end) ? .on : .off
            sub.addItem(it)
        }
        sub.addItem(.separator())
        sub.addItem(item(NSMenuItem(), "Other times…", #selector(openSettings)))
        quietItem.title = (start != nil && end != nil) ? "Quiet hours: \(start!) to \(end!)" : "Quiet hours: off"
    }

    func renderMuted() {
        let muted = snap["muted"] as? [String] ?? []
        let recent = snap["recent_projects"] as? [String] ?? []
        var names = recent
        for m in muted where !names.contains(m) { names.append(m) }
        let sub = mutedItem.submenu!
        sub.removeAllItems()
        sub.autoenablesItems = false
        if names.isEmpty {
            sub.addItem(note(NSMenuItem(title: "No projects seen in the last 2 days", action: nil, keyEquivalent: "")))
        }
        for name in names {
            let it = item(NSMenuItem(), name, #selector(toggleMute(_:)))
            it.representedObject = name
            it.state = muted.contains(name) ? .on : .off
            sub.addItem(it)
        }
        mutedItem.title = muted.isEmpty ? "Muted projects: none" : "Muted projects: \(muted.count)"
    }

    // ------------------------------------------------------------------ changing

    /// Change something through Koovi, then show what the file says now.
    func change(_ steps: [[String]]) {
        if selftest {
            steps.forEach { _ = koovi($0) }
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            steps.forEach { _ = koovi($0) }
            DispatchQueue.main.async { self.refresh() }
        }
    }

    @objc func toggleOn() { change([["set", "enabled", flag("enabled") ? "false" : "true"]]) }
    @objc func toggleCalls() { change([["set", "wait_for_mic", flag("wait_for_mic") ? "false" : "true"]]) }
    @objc func toggleAgents() { change([["set", "wait_for_agents", flag("wait_for_agents") ? "false" : "true"]]) }
    @objc func pickMode(_ it: NSMenuItem) { change([["set", "mode", it.representedObject as? String ?? "voice"]]) }

    @objc func pickQuiet(_ it: NSMenuItem) {
        let times = it.representedObject as? [String] ?? ["off", "off"]
        change([["set", "quiet_hours.start", times[0]], ["set", "quiet_hours.end", times[1]]])
    }

    @objc func toggleMute(_ it: NSMenuItem) {
        guard let name = it.representedObject as? String else { return }
        change([[it.state == .on ? "unmute" : "mute", name]])
    }

    @objc func testVoice() {
        lastNote = "Saying a sample line…"
        lastLine.title = lastNote
        change([["test"]])
        lastNote = ""
    }

    @objc func openSettings() { if !selftest { openFile(configPath) } else { print("open", configPath) } }

    @objc func openDiary() {
        let diary = (configPath as NSString).deletingLastPathComponent + "/koovi.log"
        if !selftest { openFile(diary) } else { print("open", diary) }
    }

    @objc func toggleLogin() { change([["menu", "login", flag("login", false) ? "off" : "on"]]) }

    @objc func hide() {
        _ = koovi(["set", "menu_bar", "false"])
        if !selftest { NSApp.terminate(nil) }
    }

    // ------------------------------------------------------------------ opening

    func menuWillOpen(_ m: NSMenu) {
        guard m === menu else { return }
        if peekSeconds != nil { print("menu opened"); fflush(stdout) }
        refresh()
        let t = Timer(timeInterval: 2, repeats: true) { [weak self] _ in self?.refresh() }  // the mic line stays live
        t.tolerance = 0.5
        RunLoop.main.add(t, forMode: .common)  // menus run in their own loop mode
        openTimer = t
    }

    func menuDidClose(_ m: NSMenu) {
        guard m === menu else { return }
        openTimer?.invalidate()
        openTimer = nil
    }

    func applicationDidFinishLaunching(_ n: Notification) {
        build()
        if selftest {
            runSelftest()
            return
        }
        let s = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        s.menu = menu
        status = s
        setIcon(on: true)
        refresh()
        if let seconds = peekSeconds {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                let close = Timer(timeInterval: seconds, repeats: false) { _ in
                    self.menu.cancelTracking()
                    NSApp.terminate(nil)
                }
                RunLoop.main.add(close, forMode: .common)
                if let button = s.button {
                    NSApp.activate(ignoringOtherApps: true)
                    self.menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.height + 4), in: button)
                }
            }
        }
    }

    /// Print the menu as drawn, then press every item once. Run it with a fake shim that records its arguments.
    func runSelftest() {
        let (_, out) = koovi(["settings", "--json"])
        take((try? JSONSerialization.jsonObject(with: Data(out.utf8))) as? [String: Any])
        func dump(_ m: NSMenu, _ depth: Int) {
            for it in m.items where !it.isSeparatorItem {
                let mark = it.state == .on ? "[x]" : (it.action == nil ? "   " : "[ ]")
                print(String(repeating: "  ", count: depth + it.indentationLevel) + mark + " " + it.title
                      + (it.isEnabled ? "" : "  (grey)"))
                if let sub = it.submenu { dump(sub, depth + 1) }
            }
        }
        dump(menu, 0)
        func press(_ m: NSMenu) {
            for (i, it) in m.items.enumerated() {
                if let sub = it.submenu { press(sub) } else if it.action != nil && it.isEnabled { m.performActionForItem(at: i) }
            }
        }
        press(menu)
        exit(0)
    }
}

extension NSFont {
    var bold: NSFont { NSFontManager.shared.convert(self, toHaveTrait: .boldFontMask) }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = KooviMenu()
app.delegate = delegate
_ = lockFd
app.run()

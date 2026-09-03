// KooviLight - the quiet way Koovi tells you which session needs you.
//
// Draws a pulsing coloured frame along the edges of every screen, plus a small
// list in one corner ("Checkout  done", "Payments  needs an answer"). Click-through,
// above every window, on every Space. It only reads ~/.koovi/light.json, which
// koovi.py writes; it never decides anything itself. Each item carries its own
// end time: a flash of a few seconds, then it is gone. Hides when nothing is
// left and quits after being idle for a while. One copy runs at a time.
//
// Build:  xcrun swiftc -O -o koovi-light KooviLight.swift

import AppKit

let jsonPath = CommandLine.arguments.count > 1
    ? CommandLine.arguments[1] : NSHomeDirectory() + "/.koovi/light.json"
let lockPath = (jsonPath as NSString).deletingPathExtension + ".lock"
let idleQuitSeconds: TimeInterval = 90

// one helper at a time: the second copy simply leaves
let lockFd = open(lockPath, O_CREAT | O_RDWR, 0o644)
if lockFd < 0 || flock(lockFd, LOCK_EX | LOCK_NB) != 0 { exit(0) }

struct Item {
    let label: String   // "Checkout"
    let text: String    // "done" / "needs an answer"
    let color: NSColor
    let until: Double   // unix time when this flash ends (0 = no end)
}

func color(fromHex hex: String) -> NSColor {
    var h = hex.trimmingCharacters(in: .whitespaces)
    if h.hasPrefix("#") { h.removeFirst() }
    guard h.count == 6, let v = UInt32(h, radix: 16) else { return .systemRed }
    return NSColor(red: CGFloat((v >> 16) & 0xff) / 255, green: CGFloat((v >> 8) & 0xff) / 255,
                   blue: CGFloat(v & 0xff) / 255, alpha: 1)
}

final class Overlay: NSPanel {
    let frameLayer = CAShapeLayer()
    let pill = NSView()
    let label = NSTextField(labelWithString: "")

    init(screen: NSScreen) {
        super.init(contentRect: screen.frame, styleMask: [.borderless, .nonactivatingPanel],
                   backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        ignoresMouseEvents = true                      // clicks go straight through
        level = .screenSaver                           // above everything, menu bar included
        collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        isReleasedWhenClosed = false
        hidesOnDeactivate = false

        let root = NSView(frame: NSRect(origin: .zero, size: screen.frame.size))
        root.wantsLayer = true
        contentView = root

        frameLayer.fillColor = nil
        frameLayer.lineWidth = 14
        frameLayer.shadowOpacity = 0.9
        frameLayer.shadowRadius = 22
        frameLayer.shadowOffset = .zero
        root.layer?.addSublayer(frameLayer)

        pill.wantsLayer = true
        pill.layer?.cornerRadius = 14
        pill.layer?.backgroundColor = NSColor(white: 0.05, alpha: 0.82).cgColor
        pill.layer?.borderWidth = 1
        pill.layer?.borderColor = NSColor(white: 1, alpha: 0.18).cgColor
        label.maximumNumberOfLines = 0
        label.lineBreakMode = .byWordWrapping
        pill.addSubview(label)
        root.addSubview(pill)
    }

    func show(items: [Item], pulse: Bool, corner: String, screen: NSScreen) {
        setFrame(screen.frame, display: false)
        guard let root = contentView else { return }
        root.frame = NSRect(origin: .zero, size: screen.frame.size)
        let bounds = root.bounds
        let tint = items.first?.color ?? .systemRed

        frameLayer.frame = bounds
        frameLayer.path = CGPath(roundedRect: bounds.insetBy(dx: 7, dy: 7),
                                 cornerWidth: 16, cornerHeight: 16, transform: nil)
        frameLayer.strokeColor = tint.cgColor
        frameLayer.shadowColor = tint.cgColor
        frameLayer.removeAnimation(forKey: "pulse")
        if pulse {
            let anim = CABasicAnimation(keyPath: "opacity")
            anim.fromValue = 1.0
            anim.toValue = 0.2
            anim.duration = 0.75
            anim.autoreverses = true
            anim.repeatCount = .infinity
            frameLayer.add(anim, forKey: "pulse")
        }
        frameLayer.opacity = 1.0

        let text = attributed(items)
        label.attributedStringValue = text
        let measured = text.boundingRect(with: NSSize(width: 520, height: 2000),
                                         options: [.usesLineFragmentOrigin, .usesFontLeading])
        let padX: CGFloat = 18, padY: CGFloat = 12
        label.frame = NSRect(x: padX, y: padY, width: ceil(measured.width) + 4, height: ceil(measured.height) + 4)
        let size = NSSize(width: label.frame.width + padX * 2, height: label.frame.height + padY * 2)
        pill.frame = NSRect(origin: place(size, screen: screen, corner: corner), size: size)
        pill.layer?.borderColor = tint.withAlphaComponent(0.6).cgColor
    }

    private func place(_ size: NSSize, screen: NSScreen, corner: String) -> NSPoint {
        let vis = screen.visibleFrame                 // below the menu bar, above the Dock
        let margin: CGFloat = 26
        let x0 = vis.minX - screen.frame.minX, y0 = vis.minY - screen.frame.minY
        let right = x0 + vis.width - margin - size.width
        let top = y0 + vis.height - margin - size.height
        switch corner {
        case "top-left":     return NSPoint(x: x0 + margin, y: top)
        case "bottom-left":  return NSPoint(x: x0 + margin, y: y0 + margin)
        case "bottom-right": return NSPoint(x: right, y: y0 + margin)
        default:             return NSPoint(x: right, y: top)
        }
    }

    private func attributed(_ items: [Item]) -> NSAttributedString {
        let out = NSMutableAttributedString()
        let bold = NSFont.systemFont(ofSize: 16, weight: .bold)
        let regular = NSFont.systemFont(ofSize: 16, weight: .regular)
        let para = NSMutableParagraphStyle()
        para.lineSpacing = 5
        for (i, it) in items.enumerated() {
            if i > 0 { out.append(NSAttributedString(string: "\n")) }
            out.append(NSAttributedString(string: "\u{25CF} ", attributes: [.font: bold, .foregroundColor: it.color]))
            out.append(NSAttributedString(string: it.label, attributes: [.font: bold, .foregroundColor: NSColor.white]))
            out.append(NSAttributedString(string: "   " + it.text,
                                          attributes: [.font: regular, .foregroundColor: NSColor(white: 1, alpha: 0.78)]))
        }
        out.addAttribute(.paragraphStyle, value: para, range: NSRange(location: 0, length: out.length))
        return out
    }
}

final class Controller: NSObject, NSApplicationDelegate {
    var overlays: [Overlay] = []
    var lastData = Data()
    var shownUntil: [Double] = []
    var emptySince: Date? = Date()

    func applicationDidFinishLaunching(_ note: Notification) {
        rebuild()
        NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main
        ) { _ in self.rebuild(); self.poll(force: true) }
        Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { _ in self.poll() }
        poll(force: true)
    }

    func rebuild() {
        overlays.forEach { $0.orderOut(nil) }
        overlays = NSScreen.screens.map { Overlay(screen: $0) }
    }

    func poll(force: Bool = false) {
        let now = Date().timeIntervalSince1970
        let expired = shownUntil.contains { $0 > 0 && $0 <= now }   // a flash ran out: redraw
        let data = (try? Data(contentsOf: URL(fileURLWithPath: jsonPath))) ?? Data()
        if !force && data == lastData && !expired { quitIfIdle(); return }
        lastData = data

        var items: [Item] = []
        var pulse = true
        var corner = "top-right"
        if let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] {
            pulse = obj["pulse"] as? Bool ?? true
            corner = obj["corner"] as? String ?? corner
            for it in obj["items"] as? [[String: Any]] ?? [] {
                let until = it["until"] as? Double ?? 0
                if until > 0 && until <= now { continue }              // its few seconds are over
                items.append(Item(label: it["label"] as? String ?? "?",
                                  text: it["text"] as? String ?? "",
                                  color: color(fromHex: it["color"] as? String ?? "#ff3b30"),
                                  until: until))
            }
        }
        shownUntil = items.map { $0.until }

        if items.isEmpty {
            overlays.forEach { $0.orderOut(nil) }
            if emptySince == nil { emptySince = Date() }
        } else {
            emptySince = nil
            for (overlay, screen) in zip(overlays, NSScreen.screens) {
                overlay.show(items: items, pulse: pulse, corner: corner, screen: screen)
                overlay.orderFrontRegardless()
            }
        }
        quitIfIdle()
    }

    func quitIfIdle() {
        if let since = emptySince, Date().timeIntervalSince(since) > idleQuitSeconds { exit(0) }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)   // no Dock icon, no menu, never steals focus
let controller = Controller()
app.delegate = controller
app.run()

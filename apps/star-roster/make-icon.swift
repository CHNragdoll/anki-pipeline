import AppKit

let target = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)

for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let canvas = NSImage(size: NSSize(width: pixels, height: pixels), flipped: false) { _ in
            let width = CGFloat(pixels)
            let tile = NSBezierPath(roundedRect: NSRect(x: width * 0.09, y: width * 0.09,
                                                        width: width * 0.82, height: width * 0.82),
                                    xRadius: width * 0.19, yRadius: width * 0.19)
            NSGradient(starting: NSColor(srgbRed: 0.32, green: 0.48, blue: 0.98, alpha: 1),
                       ending: NSColor(srgbRed: 0.16, green: 0.28, blue: 0.73, alpha: 1))!
                .draw(in: tile, angle: -65)
            let star = NSBezierPath()
            for index in 0..<10 {
                let angle = CGFloat.pi / 2 + CGFloat(index) * CGFloat.pi / 5
                let radius = width * (index.isMultiple(of: 2) ? 0.26 : 0.122)
                let point = NSPoint(x: width * 0.5 + cos(angle) * radius, y: width * 0.48 + sin(angle) * radius)
                if index == 0 { star.move(to: point) } else { star.line(to: point) }
            }
            star.close()
            NSColor.white.setFill()
            star.fill()
            return true
        }
        let rect = NSRect(x: 0, y: 0, width: pixels, height: pixels)
        var proposedRect = rect
        let image = canvas.cgImage(forProposedRect: &proposedRect, context: nil, hints: nil)!
        let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])!
        let suffix = scale == 2 ? "@2x" : ""
        try png.write(to: target.appendingPathComponent("icon_\(size)x\(size)\(suffix).png"))
    }
}

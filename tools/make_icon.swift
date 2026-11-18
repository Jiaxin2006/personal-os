// Draw the 1024px app icon master: a seven-day ring, five days lit (the weekly
// effective-day idea). Original artwork; SF Symbols may not be used in app icons.
// Usage: swift tools/make_icon.swift <output.png>
// tools/build_macos.py turns the master into AppIcon.icns with sips and iconutil.
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let size = 1024
let space = CGColorSpace(name: CGColorSpace.sRGB)!
let context = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
                        space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!

func color(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> CGColor {
    CGColor(colorSpace: space, components: [r, g, b, a])!
}

// macOS icon grid: 824px rounded square centred on the 1024 canvas.
let tile = CGRect(x: 100, y: 100, width: 824, height: 824)
let shape = CGPath(roundedRect: tile, cornerWidth: 185, cornerHeight: 185, transform: nil)
context.saveGState()
context.setShadow(offset: CGSize(width: 0, height: -12), blur: 28, color: color(0, 0, 0, 0.32))
context.addPath(shape)
context.setFillColor(color(0.33, 0.31, 0.84))
context.fillPath()
context.restoreGState()

context.saveGState()
context.addPath(shape)
context.clip()
let gradient = CGGradient(colorsSpace: space, colors: [color(0.42, 0.40, 0.95), color(0.20, 0.17, 0.62)] as CFArray,
                          locations: [0, 1])!
context.drawLinearGradient(gradient, start: CGPoint(x: 512, y: 924), end: CGPoint(x: 512, y: 100), options: [])
context.restoreGState()

let center = CGPoint(x: 512, y: 512)
let radius: CGFloat = 255
let step = 2 * CGFloat.pi / 7
let gap: CGFloat = 0.36  // radians; round caps eat into it
context.setLineWidth(62)
context.setLineCap(.round)
for day in 0..<7 {
    // Clockwise from twelve o'clock.
    let start = CGFloat.pi / 2 - CGFloat(day) * step - gap / 2
    let end = start - step + gap
    context.setStrokeColor(day < 5 ? color(1, 1, 1) : color(1, 1, 1, 0.28))
    context.addArc(center: center, radius: radius, startAngle: start, endAngle: end, clockwise: true)
    context.strokePath()
}
context.setFillColor(color(1, 1, 1))
context.fillEllipse(in: CGRect(x: center.x - 62, y: center.y - 62, width: 124, height: 124))

let output = URL(fileURLWithPath: CommandLine.arguments[1])
let destination = CGImageDestinationCreateWithURL(output as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(destination, context.makeImage()!, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("could not write \(output.path)") }

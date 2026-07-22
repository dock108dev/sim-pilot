using System;
using System.IO;
using System.Text;

namespace SimPilot.GameBridge;

public static class LengthPrefixedFrame
{
    public static string Read(Stream stream, int maximumBytes = BridgeContract.MaximumMessageBytes)
    {
        if (stream is null) throw new ArgumentNullException(nameof(stream));
        if (maximumBytes < 1) throw new ArgumentOutOfRangeException(nameof(maximumBytes));
        var prefix = ReadExact(stream, 4);
        var length = ((long)prefix[0] << 24) | ((long)prefix[1] << 16) | ((long)prefix[2] << 8) | prefix[3];
        if (length < 1 || length > maximumBytes) throw new InvalidDataException($"frame length must be between 1 and {maximumBytes} bytes");
        var payload = ReadExact(stream, checked((int)length));
        return new UTF8Encoding(false, true).GetString(payload);
    }

    public static void Write(Stream stream, string message, int maximumBytes = BridgeContract.MaximumMessageBytes)
    {
        if (stream is null) throw new ArgumentNullException(nameof(stream));
        if (message is null) throw new ArgumentNullException(nameof(message));
        var payload = new UTF8Encoding(false, true).GetBytes(message);
        if (payload.Length < 1 || payload.Length > maximumBytes) throw new InvalidDataException($"frame length must be between 1 and {maximumBytes} bytes");
        var prefix = new[] { (byte)(payload.Length >> 24), (byte)(payload.Length >> 16), (byte)(payload.Length >> 8), (byte)payload.Length };
        stream.Write(prefix, 0, prefix.Length);
        stream.Write(payload, 0, payload.Length);
        stream.Flush();
    }

    private static byte[] ReadExact(Stream stream, int length)
    {
        var result = new byte[length];
        var offset = 0;
        while (offset < length)
        {
            var count = stream.Read(result, offset, length - offset);
            if (count == 0) throw new EndOfStreamException("connection closed during bridge frame");
            offset += count;
        }
        return result;
    }
}

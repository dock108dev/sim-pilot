using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace SimPilot.GameBridge;

public enum JsonKind
{
    Null,
    Boolean,
    Integer,
    Number,
    String,
    Array,
    Object,
}

public sealed class JsonValue
{
    private JsonValue(JsonKind kind, object? value)
    {
        Kind = kind;
        Value = value;
    }

    public JsonKind Kind { get; }
    public object? Value { get; }

    public static JsonValue Null() => new(JsonKind.Null, null);
    public static JsonValue Boolean(bool value) => new(JsonKind.Boolean, value);
    public static JsonValue Integer(long value) => new(JsonKind.Integer, value);
    public static JsonValue Number(double value) => new(JsonKind.Number, value);
    public static JsonValue String(string value) => new(JsonKind.String, value ?? throw new ArgumentNullException(nameof(value)));
    public static JsonValue Array(params JsonValue[] values) => new(JsonKind.Array, new List<JsonValue>(values));
    public static JsonValue Object(IDictionary<string, JsonValue> values) => new(JsonKind.Object, new Dictionary<string, JsonValue>(values, StringComparer.Ordinal));

    public bool AsBoolean() => Kind == JsonKind.Boolean ? (bool)Value! : throw TypeError("boolean");
    public long AsInteger() => Kind == JsonKind.Integer ? (long)Value! : throw TypeError("integer");
    public double AsNumber() => Kind == JsonKind.Number ? (double)Value! : Kind == JsonKind.Integer ? AsInteger() : throw TypeError("number");
    public string AsString() => Kind == JsonKind.String ? (string)Value! : throw TypeError("string");
    public IReadOnlyList<JsonValue> AsArray() => Kind == JsonKind.Array ? (List<JsonValue>)Value! : throw TypeError("array");
    public IReadOnlyDictionary<string, JsonValue> AsObject() => Kind == JsonKind.Object ? (Dictionary<string, JsonValue>)Value! : throw TypeError("object");

    private FormatException TypeError(string expected) => new($"expected JSON {expected}, found {Kind.ToString().ToLowerInvariant()}");
}

public static class StrictJson
{
    public static JsonValue Parse(string text)
    {
        if (text is null) throw new ArgumentNullException(nameof(text));
        var parser = new Parser(text);
        var result = parser.ReadValue();
        parser.SkipWhitespace();
        if (!parser.AtEnd) throw new FormatException("unexpected content after JSON value");
        return result;
    }

    public static string Serialize(JsonValue value)
    {
        var output = new StringBuilder();
        Write(value, output);
        return output.ToString();
    }

    private static void Write(JsonValue value, StringBuilder output)
    {
        switch (value.Kind)
        {
            case JsonKind.Null: output.Append("null"); return;
            case JsonKind.Boolean: output.Append(value.AsBoolean() ? "true" : "false"); return;
            case JsonKind.Integer: output.Append(value.AsInteger().ToString(CultureInfo.InvariantCulture)); return;
            case JsonKind.Number: output.Append(value.AsNumber().ToString("0.0################", CultureInfo.InvariantCulture)); return;
            case JsonKind.String: WriteString(value.AsString(), output); return;
            case JsonKind.Array:
                output.Append('[');
                var firstArray = true;
                foreach (var item in value.AsArray())
                {
                    if (!firstArray) output.Append(',');
                    firstArray = false;
                    Write(item, output);
                }
                output.Append(']');
                return;
            case JsonKind.Object:
                output.Append('{');
                var keys = new List<string>(value.AsObject().Keys);
                keys.Sort(StringComparer.Ordinal);
                var firstObject = true;
                foreach (var key in keys)
                {
                    if (!firstObject) output.Append(',');
                    firstObject = false;
                    WriteString(key, output);
                    output.Append(':');
                    Write(value.AsObject()[key], output);
                }
                output.Append('}');
                return;
            default: throw new InvalidOperationException("unknown JSON kind");
        }
    }

    private static void WriteString(string value, StringBuilder output)
    {
        output.Append('"');
        foreach (var character in value)
        {
            switch (character)
            {
                case '"': output.Append("\\\""); break;
                case '\\': output.Append("\\\\"); break;
                case '\b': output.Append("\\b"); break;
                case '\f': output.Append("\\f"); break;
                case '\n': output.Append("\\n"); break;
                case '\r': output.Append("\\r"); break;
                case '\t': output.Append("\\t"); break;
                default:
                    if (character < 0x20)
                    {
                        output.Append("\\u");
                        output.Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                    }
                    else output.Append(character);
                    break;
            }
        }
        output.Append('"');
    }

    private sealed class Parser
    {
        private readonly string text;
        private int index;

        internal Parser(string text) => this.text = text;
        internal bool AtEnd => index == text.Length;
        internal void SkipWhitespace()
        {
            while (!AtEnd && (text[index] == ' ' || text[index] == '\t' || text[index] == '\r' || text[index] == '\n')) index++;
        }

        internal JsonValue ReadValue()
        {
            SkipWhitespace();
            if (AtEnd) throw new FormatException("unexpected end of JSON");
            return text[index] switch
            {
                'n' => ReadLiteral("null", JsonValue.Null()),
                't' => ReadLiteral("true", JsonValue.Boolean(true)),
                'f' => ReadLiteral("false", JsonValue.Boolean(false)),
                '"' => JsonValue.String(ReadString()),
                '[' => ReadArray(),
                '{' => ReadObject(),
                '-' => ReadInteger(),
                >= '0' and <= '9' => ReadInteger(),
                _ => throw new FormatException($"unexpected JSON character at offset {index}"),
            };
        }

        private JsonValue ReadLiteral(string literal, JsonValue value)
        {
            if (index + literal.Length > text.Length || string.CompareOrdinal(text, index, literal, 0, literal.Length) != 0)
                throw new FormatException($"invalid JSON literal at offset {index}");
            index += literal.Length;
            return value;
        }

        private JsonValue ReadInteger()
        {
            var start = index;
            if (text[index] == '-') index++;
            if (AtEnd) throw new FormatException("incomplete JSON number");
            if (text[index] == '0') index++;
            else
            {
                if (text[index] < '1' || text[index] > '9') throw new FormatException("invalid JSON integer");
                while (!AtEnd && text[index] >= '0' && text[index] <= '9') index++;
            }
            var integerEnd = index;
            if (!AtEnd && text[index] == '.')
            {
                index++;
                var fractionStart = index;
                while (!AtEnd && text[index] >= '0' && text[index] <= '9') index++;
                if (fractionStart == index) throw new FormatException("invalid JSON fraction");
            }
            if (!AtEnd && (text[index] == 'e' || text[index] == 'E'))
            {
                index++;
                if (!AtEnd && (text[index] == '+' || text[index] == '-')) index++;
                var exponentStart = index;
                while (!AtEnd && text[index] >= '0' && text[index] <= '9') index++;
                if (exponentStart == index) throw new FormatException("invalid JSON exponent");
            }
            var raw = text.Substring(start, index - start);
            if (index != integerEnd)
            {
                if (!double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var number) || double.IsInfinity(number) || double.IsNaN(number)) throw new FormatException("JSON number is out of range");
                return JsonValue.Number(number);
            }
            if (!long.TryParse(raw, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var value))
                throw new FormatException("JSON integer is out of range");
            return JsonValue.Integer(value);
        }

        private string ReadString()
        {
            if (text[index++] != '"') throw new InvalidOperationException();
            var result = new StringBuilder();
            while (!AtEnd)
            {
                var character = text[index++];
                if (character == '"') return result.ToString();
                if (character < 0x20) throw new FormatException("unescaped control character in JSON string");
                if (character != '\\')
                {
                    result.Append(character);
                    continue;
                }
                if (AtEnd) throw new FormatException("incomplete JSON escape");
                var escaped = text[index++];
                switch (escaped)
                {
                    case '"': result.Append('"'); break;
                    case '\\': result.Append('\\'); break;
                    case '/': result.Append('/'); break;
                    case 'b': result.Append('\b'); break;
                    case 'f': result.Append('\f'); break;
                    case 'n': result.Append('\n'); break;
                    case 'r': result.Append('\r'); break;
                    case 't': result.Append('\t'); break;
                    case 'u': result.Append(ReadUnicode()); break;
                    default: throw new FormatException("invalid JSON escape");
                }
            }
            throw new FormatException("unterminated JSON string");
        }

        private char ReadUnicode()
        {
            if (index + 4 > text.Length) throw new FormatException("incomplete Unicode escape");
            if (!ushort.TryParse(text.Substring(index, 4), NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture, out var value))
                throw new FormatException("invalid Unicode escape");
            index += 4;
            return (char)value;
        }

        private JsonValue ReadArray()
        {
            index++;
            var values = new List<JsonValue>();
            SkipWhitespace();
            if (!AtEnd && text[index] == ']') { index++; return JsonValue.Array(); }
            while (true)
            {
                values.Add(ReadValue());
                SkipWhitespace();
                if (AtEnd) throw new FormatException("unterminated JSON array");
                var separator = text[index++];
                if (separator == ']') return JsonValue.Array(values.ToArray());
                if (separator != ',') throw new FormatException("expected comma in JSON array");
            }
        }

        private JsonValue ReadObject()
        {
            index++;
            var values = new Dictionary<string, JsonValue>(StringComparer.Ordinal);
            SkipWhitespace();
            if (!AtEnd && text[index] == '}') { index++; return JsonValue.Object(values); }
            while (true)
            {
                SkipWhitespace();
                if (AtEnd || text[index] != '"') throw new FormatException("expected object key");
                var key = ReadString();
                SkipWhitespace();
                if (AtEnd || text[index++] != ':') throw new FormatException("expected colon after object key");
                var value = ReadValue();
                if (values.ContainsKey(key)) throw new FormatException($"duplicate JSON key: {key}");
                values.Add(key, value);
                SkipWhitespace();
                if (AtEnd) throw new FormatException("unterminated JSON object");
                var separator = text[index++];
                if (separator == '}') return JsonValue.Object(values);
                if (separator != ',') throw new FormatException("expected comma in JSON object");
            }
        }
    }
}

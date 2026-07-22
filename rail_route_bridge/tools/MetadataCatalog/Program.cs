using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;

if (args.Length is < 1 or > 2)
{
    Console.Error.WriteLine("usage: MetadataCatalog <managed-assembly> [namespace-or-type-filter]");
    return 2;
}

var filter = args.Length == 2 ? args[1] : string.Empty;
using var stream = File.OpenRead(args[0]);
using var pe = new PEReader(stream);
if (!pe.HasMetadata)
{
    Console.Error.WriteLine("assembly does not contain managed metadata");
    return 2;
}

var reader = pe.GetMetadataReader();
var typeNames = new TypeNameProvider(reader);
foreach (var handle in reader.TypeDefinitions)
{
    var type = reader.GetTypeDefinition(handle);
    var name = reader.GetString(type.Name);
    var typeNamespace = reader.GetString(type.Namespace);
    var qualifiedName = string.IsNullOrEmpty(typeNamespace) ? name : $"{typeNamespace}.{name}";
    if (!qualifiedName.Contains(filter, StringComparison.OrdinalIgnoreCase)) continue;

    Console.WriteLine($"TYPE {TypeVisibility(type.Attributes)} {qualifiedName}");
    foreach (var propertyHandle in type.GetProperties())
    {
        var property = reader.GetPropertyDefinition(propertyHandle);
        var signature = property.DecodeSignature(typeNames, genericContext: null);
        Console.WriteLine($"  PROPERTY {signature.ReturnType} {reader.GetString(property.Name)}");
    }
    foreach (var fieldHandle in type.GetFields())
    {
        var field = reader.GetFieldDefinition(fieldHandle);
        var fieldType = field.DecodeSignature(typeNames, genericContext: null);
        Console.WriteLine($"  FIELD {FieldVisibility(field.Attributes)} {fieldType} {reader.GetString(field.Name)}");
    }
    foreach (var methodHandle in type.GetMethods())
    {
        var method = reader.GetMethodDefinition(methodHandle);
        if ((method.Attributes & MethodAttributes.SpecialName) != 0) continue;
        var signature = method.DecodeSignature(typeNames, genericContext: null);
        Console.WriteLine($"  METHOD {MethodVisibility(method.Attributes)} {signature.ReturnType} {reader.GetString(method.Name)}({string.Join(", ", signature.ParameterTypes)})");
    }
}

return 0;

static string TypeVisibility(TypeAttributes attributes) =>
    (attributes & TypeAttributes.VisibilityMask) switch
    {
        TypeAttributes.Public or TypeAttributes.NestedPublic => "public",
        TypeAttributes.NestedFamily or TypeAttributes.NestedFamORAssem => "protected",
        _ => "nonpublic",
    };

static string FieldVisibility(FieldAttributes attributes) =>
    (attributes & FieldAttributes.FieldAccessMask) switch
    {
        FieldAttributes.Public => "public",
        FieldAttributes.Family or FieldAttributes.FamORAssem => "protected",
        _ => "nonpublic",
    };

static string MethodVisibility(MethodAttributes attributes) =>
    (attributes & MethodAttributes.MemberAccessMask) switch
    {
        MethodAttributes.Public => "public",
        MethodAttributes.Family or MethodAttributes.FamORAssem => "protected",
        _ => "nonpublic",
    };

sealed class TypeNameProvider(MetadataReader reader) : ISignatureTypeProvider<string, object?>
{
    public string GetArrayType(string elementType, ArrayShape shape) => $"{elementType}[{new string(',', shape.Rank - 1)}]";
    public string GetByReferenceType(string elementType) => $"ref {elementType}";
    public string GetFunctionPointerType(MethodSignature<string> signature) => "function-pointer";
    public string GetGenericInstantiation(string genericType, System.Collections.Immutable.ImmutableArray<string> typeArguments) => $"{genericType}<{string.Join(",", typeArguments)}>";
    public string GetGenericMethodParameter(object? genericContext, int index) => $"!!{index}";
    public string GetGenericTypeParameter(object? genericContext, int index) => $"!{index}";
    public string GetModifiedType(string modifierType, string unmodifiedType, bool isRequired) => unmodifiedType;
    public string GetPinnedType(string elementType) => elementType;
    public string GetPointerType(string elementType) => $"{elementType}*";
    public string GetPrimitiveType(PrimitiveTypeCode typeCode) => typeCode.ToString();
    public string GetSZArrayType(string elementType) => $"{elementType}[]";
    public string GetTypeFromDefinition(MetadataReader _, TypeDefinitionHandle handle, byte rawTypeKind)
    {
        var definition = reader.GetTypeDefinition(handle);
        return Qualified(reader.GetString(definition.Namespace), reader.GetString(definition.Name));
    }
    public string GetTypeFromReference(MetadataReader _, TypeReferenceHandle handle, byte rawTypeKind)
    {
        var reference = reader.GetTypeReference(handle);
        return Qualified(reader.GetString(reference.Namespace), reader.GetString(reference.Name));
    }
    public string GetTypeFromSpecification(MetadataReader _, object? genericContext, TypeSpecificationHandle handle, byte rawTypeKind) => reader.GetTypeSpecification(handle).DecodeSignature(this, genericContext);
    private static string Qualified(string typeNamespace, string name) => string.IsNullOrEmpty(typeNamespace) ? name : $"{typeNamespace}.{name}";
}

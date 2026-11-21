using MicroCom.CodeGenerator;
using System.Text;

if (args.Length != 2)
{
    Console.Error.WriteLine("Usage: headers <input.idl> <output.h>");
    return 2;
}

var header = MicroComCodeGenerator.Parse(File.ReadAllText(args[0])).GenerateCppHeader();
var output = Path.GetFullPath(args[1]);
Directory.CreateDirectory(Path.GetDirectoryName(output)!);
File.WriteAllText(output, header, new UTF8Encoding(false));
return 0;

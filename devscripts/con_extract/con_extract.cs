// con-extract — extract raw files from an STFS CON using GameArchives (the
// exact library ForgeTool uses). Research tool for the charting-accuracy
// loop: pulls the official DLC chart (notes.mid, songs.dta, milo) out of an
// official RB3 CON so we can diff our auto chart against Harmonix's.
//
// Build (mono; against the prebuilt GameArchives.dll from the vendored
// LibForge deps — GameArchives.csproj targets net35 which plain dotnet can't
// build without developer packs):
//   cd devscripts/con_extract
//   mcs con_extract.cs -r:../../tools/libforge/Dependencies/GameArchives/Library/bin/Release/GameArchives.dll -out:con-extract.exe
//   # (GameArchives.dll must sit next to con-extract.exe at runtime)
// Usage:  mono devscripts/con_extract/con-extract.exe <input.con> <output_dir> [name-filter]

using System;
using System.IO;
using GameArchives;
using GameArchives.STFS;

class ConExtract
{
  static int Main(string[] args)
  {
    if (args.Length < 2)
    {
      Console.Error.WriteLine("usage: con-extract <input.con> <output_dir> [name-filter]");
      return 2;
    }
    var pkg = STFSPackage.OpenFile(GameArchives.Util.LocalFile(args[0]));
    if (pkg == null)
    {
      Console.Error.WriteLine("ERROR: not a readable STFS package");
      return 1;
    }
    Console.WriteLine("STFS type: " + pkg.Type);
    var filter = args.Length > 2 ? args[2].ToLowerInvariant() : null;
    int n = 0;
    ExtractDir(pkg.RootDirectory, "", args[1], filter, ref n);
    Console.WriteLine($"extracted {n} file(s) to {args[1]}");
    return 0;
  }

  static void ExtractDir(IDirectory dir, string prefix, string outDir, string filter, ref int n)
  {
    foreach (var f in dir.Files)
    {
      if (filter != null && !f.Name.ToLowerInvariant().Contains(filter)) continue;
      var dest = Path.Combine(outDir, (prefix + f.Name).Replace('/', Path.DirectorySeparatorChar));
      Directory.CreateDirectory(Path.GetDirectoryName(dest));
      using (var s = f.GetStream())
      using (var o = File.Create(dest))
        s.CopyTo(o);
      Console.WriteLine($"  {prefix}{f.Name}  ({f.Size} bytes)");
      n++;
    }
    foreach (var d in dir.Dirs)
      ExtractDir(d, prefix + d.Name + "/", outDir, filter, ref n);
  }
}

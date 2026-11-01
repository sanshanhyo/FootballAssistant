using System.Text.Json;
using FootballAssistant.GameBridge;
internal static class FinitePrivateFileWriterTests
{
    private static void Check(bool value,string message)
    { if (!value) throw new Exception("Finite atomic status: " + message); }
    internal static void Run()
    {
        var root = Path.Combine(Path.GetTempPath(), "finite-status-owned-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var writer = new FinitePrivateFileWriter(root);
            var path = Path.Combine(root,"finite-rows-state.json");
            writer.Write("finite-rows-state.json",new { sequence=0, payload=new string('x',2048) });
            var writes = Task.Run(() =>
            {
                for(var i=1;i<=32;i++) writer.Write("finite-rows-state.json",new { sequence=i, payload=new string('x',2048) });
            });
            var reads=0;
            do
            {
                using var stream = new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete);
                using var document = JsonDocument.Parse(stream);
                Check(document.RootElement.GetProperty("sequence").GetInt32() is >=0 and <=32 &&
                    document.RootElement.GetProperty("payload").GetString() == new string('x',2048), "every observed snapshot is complete JSON");
                reads++; Thread.Sleep(1);
            } while(!writes.IsCompleted);
            writes.GetAwaiter().GetResult();
            using(var final=JsonDocument.Parse(File.ReadAllBytes(path)))
                Check(final.RootElement.GetProperty("sequence").GetInt32()==32,"last completed atomic replacement retained");
            Check(reads>0 && !Directory.EnumerateFiles(root,"*.tmp").Any(),"own temp files cleaned after replacement");
            foreach(var name in new[]{"../escape.json","request.json",Path.Combine(root,"other.json")})
            {
                var denied=false;
                try { writer.Write(name,new { illegal=true }); } catch(ArgumentException) { denied=true; }
                Check(denied,"only three fixed status names accepted");
            }
            // An owned directory at the destination forces rename failure, without symlinks or foreign files.
            Directory.CreateDirectory(Path.Combine(root,"module-status.json"));
            var failed=false;
            try { writer.Write("module-status.json",new { state="ready" }); }
            catch(IOException) { failed=true; }
            catch(UnauthorizedAccessException) { failed=true; }
            Check(failed && !Directory.EnumerateFiles(root,"*.tmp").Any(),"rename failure cleans its own temp and propagates failure");
            writer.Write("session.json",new { mode="owned-test-only" });
            Check(File.Exists(Path.Combine(root,"session.json")),"writer remains usable for other fixed status file");
        }
        finally { Directory.Delete(root,recursive:true); }
        Console.WriteLine("Finite atomic status owned-file fixtures registered; no Windows/game calls.");
    }
}

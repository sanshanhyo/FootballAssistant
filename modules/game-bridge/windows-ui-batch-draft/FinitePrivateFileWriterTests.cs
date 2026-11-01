using System.Text.Json;
using FootballAssistant.GameBridge;
internal static class FinitePrivateFileWriterTests
{
    private static void Check(bool value,string message)
    { if (!value) throw new Exception("Finite atomic status: " + message); }
    // Test reader protocol only. The writer and production ACL checks are unchanged.
    private static bool SharingMayDefer(IOException error, bool writerWasActive, bool windows) =>
        windows && writerWasActive && error.HResult == unchecked((int)0x80070020);
    internal static void Run()
    {
        var root = Path.Combine(Path.GetTempPath(), "finite-status-owned-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var writer = new FinitePrivateFileWriter(root);
            var path = Path.Combine(root,"finite-rows-state.json");
            writer.Write("finite-rows-state.json",new { sequence=0, payload=new string('x',2048) });
            // Deterministic open-reader case, not merely probabilistic scheduling.
            using (var held = new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))
            {
                writer.Write("finite-rows-state.json",new { sequence=-1, payload="replacement" });
                using var oldSnapshot = JsonDocument.Parse(held);
                Check(oldSnapshot.RootElement.GetProperty("sequence").GetInt32()==0,
                    "already-open reader retains complete old snapshot while path is replaced");
                using var newSnapshot = JsonDocument.Parse(File.ReadAllBytes(path));
                Check(newSnapshot.RootElement.GetProperty("sequence").GetInt32()==-1,
                    "new readers see complete replacement without deleting old snapshot first");
            }
            if (OperatingSystem.IsWindows())
            {
                using var denied = new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.Read);
                var blocked=false;
                try { writer.Write("finite-rows-state.json",new { sequence=-2 }); }
                catch(IOException) { blocked=true; }
                catch(UnauthorizedAccessException) { blocked=true; }
                Check(blocked,"reader without delete sharing is respected, not bypassed or retried");
                using var retained = JsonDocument.Parse(denied);
                Check(retained.RootElement.GetProperty("sequence").GetInt32()==-1,
                    "denied replacement preserves the prior complete snapshot");
                Check(!Directory.EnumerateFiles(root,"*.tmp").Any(),"denied replacement cleans only its owned temporary");
            }
            writer.Write("finite-rows-state.json",new { sequence=0, payload=new string('x',2048) });
            var writes = Task.Run(() =>
            {
                for(var i=1;i<=32;i++) writer.Write("finite-rows-state.json",new { sequence=i, payload=new string('x',2048) });
            });
            var reads=0; var transientMissing=0; var transientSharing=0; var attempts=0;
            Check(SharingMayDefer(new IOException("synthetic sharing",unchecked((int)0x80070020)),true,true) &&
                !SharingMayDefer(new IOException("synthetic sharing",unchecked((int)0x80070020)),false,true) &&
                !SharingMayDefer(new IOException("synthetic sharing",unchecked((int)0x80070020)),true,false) &&
                !SharingMayDefer(new IOException("synthetic access denied",unchecked((int)0x80070005)),true,true) &&
                !SharingMayDefer(new IOException("synthetic lock violation",unchecked((int)0x80070021)),true,true) &&
                !SharingMayDefer(new IOException("synthetic generic IO"),true,true),
                "only exact Windows sharing32 during known active writer is deferrable, not permissions/locks/general IO");
            var readDeadline=System.Diagnostics.Stopwatch.StartNew();
            bool ReadComplete(bool writerWasActive)
            {
                FileStream stream;
                try
                {
                    stream = new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete);
                }
                catch(FileNotFoundException) when(writerWasActive)
                {
                    // Observed Windows ReplaceFile namespace gap: no observation,
                    // no freshness advancement. Permissions/JSON/other IO errors propagate.
                    transientMissing++;
                    return false;
                }
                catch(IOException error) when(SharingMayDefer(error,writerWasActive,OperatingSystem.IsWindows()))
                {
                    // ReplaceFile opens the replacement without sharing; a concurrent
                    // pathname open may race it. Exact code only, never ACL/other IO.
                    transientSharing++;
                    if(transientSharing==1)
                        Console.WriteLine($"Finite status reader observed hresult=0x{unchecked((uint)error.HResult):X8}, win32={error.HResult & 0xffff}; active-writer deferral, no freshness.");
                    return false;
                }
                using(stream)
                {
                    // Only open races can defer. Read/parse/validation errors always propagate.
                    using var document = JsonDocument.Parse(stream);
                    Check(document.RootElement.GetProperty("sequence").GetInt32() is >=0 and <=32 &&
                        document.RootElement.GetProperty("payload").GetString() == new string('x',2048),
                        "every successfully opened snapshot is complete JSON");
                    return true;
                }
            }
            do
            {
                Check(++attempts<=4096 && readDeadline.Elapsed<TimeSpan.FromSeconds(10),
                    "concurrent reader deferral has a finite attempt/time bound");
                var writerWasActive=!writes.IsCompleted; // Evidence captured BEFORE this open attempt.
                if(ReadComplete(writerWasActive)) reads++;
                Thread.Sleep(1);
            } while(!writes.IsCompleted);
            writes.GetAwaiter().GetResult(); // Never hide a writer failure behind transient read deferral.
            using(var final=JsonDocument.Parse(File.ReadAllBytes(path))) // Unconditional: permanent absence fails.
                Check(final.RootElement.GetProperty("sequence").GetInt32()==32 &&
                    final.RootElement.GetProperty("payload").GetString()==new string('x',2048),
                    "completed writer leaves exact final complete snapshot");
            Check(reads>0 && !Directory.EnumerateFiles(root,"*.tmp").Any(),"own temp files cleaned after replacement");
            if(OperatingSystem.IsWindows())
            {
                using var exclusive=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.None);
                var permissionFailed=false;
                try { ReadComplete(writerWasActive:false); }
                catch(IOException) { permissionFailed=true; }
                catch(UnauthorizedAccessException) { permissionFailed=true; }
                Check(permissionFailed,"sharing/permission failures after writer completion are fatal, never deferred");
            }
            File.Delete(path); // Owned fixture file only: a completed writer cannot excuse permanent absence.
            var missingFailed=false;
            try { ReadComplete(writerWasActive:false); } catch(FileNotFoundException) { missingFailed=true; }
            Check(missingFailed,"missing status after writer completion must fail, not defer forever");
            writer.Write("finite-rows-state.json",new { sequence=32, payload=new string('x',2048) });
            Console.WriteLine($"Finite status reader: complete_reads={reads}, transient_missing={transientMissing}, transient_sharing={transientSharing}, attempts={attempts}; no freshness on deferral.");
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

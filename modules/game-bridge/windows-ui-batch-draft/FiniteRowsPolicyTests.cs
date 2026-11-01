namespace FootballAssistant.GameBridge;
internal static class FiniteRowsPolicyTests
{
    private static void Check(bool value,string reason) { if(!value) throw new Exception("Finite row policy fixture: " + reason); }
    internal static void Run()
    {
        var now = DateTimeOffset.Parse("2026-11-01T00:00:00Z");
        var context = new SmokeContext(12,"fixture",new string('a',64),new string('b',64),"FixtureWindow",34);
        var identity = new WindowsThreadIdentity(0,12,0,34,0,34,false) {
            WindowScanStatus="complete",WindowScanCount=1,
            WindowCandidates=new[]{new WindowsWindowDiagnostic(56,12,34,true,"FixtureWindow",true,0,true,true,10,10,0)} };
        FiniteRowsApproval Approval(bool enabled=true) => new(context,Guid.NewGuid(),Guid.NewGuid(),Guid.NewGuid(),Guid.NewGuid(),now,now.AddSeconds(120),true,enabled);
        FiniteRowsRequest Request(FiniteRowsPolicy p,int index=0) => new(4,p.Approval.BatchId,p.Approval.PageEpoch,index,
            index==0?p.Approval.FirstNonce:p.Approval.SecondNonce,p.ApprovalSha256);
        void Reject(FiniteRowsApproval a) { var failed=false; try{_=new FiniteRowsPolicy(a);}catch(ArgumentException){failed=true;} Check(failed,"invalid manifest"); }
        var off=new FiniteRowsPolicy(Approval(false));Check(off.TryBegin(Request(off),identity,now,0) is null && !off.Consumed,"default off");
        var valid=Approval();Reject(valid with{SecondNonce=valid.FirstNonce});Reject(valid with{PageEpoch=Guid.Empty});
        Reject(valid with{StableProfileAsserted=false});Reject(valid with{ExpiresAt=now.AddSeconds(121)});
        Reject(valid with{Context=context with{EntryThread=0}});
        var p=new FiniteRowsPolicy(valid);var original=Request(p);var first=p.TryBegin(original,identity,now,0)!;
        Check(first.RowStart==0 && first.RowCount==2 && first.SelectionProfile=="goalkeeper_rows0_1" && first.MaximumOperations==2048,"fixed first manifest chunk");
        Check(p.CheckActive(first,now.AddMilliseconds(500),500),"composed active gate");
        Check(p.Finish(first,2048,1000,true,now.AddSeconds(1),1000),"first exact budget accepted");
        Check(!p.Terminal && p.NextChunkIndex==1 && p.NextEligibleMonotonicMilliseconds==3000,"two-second monotonic cooldown from finish");
        var second=p.TryBegin(Request(p,1),identity,now.AddSeconds(3),3000)!;
        Check(second.RowStart==2 && second.SelectionProfile=="goalkeeper_rows2_3","fixed second chunk");
        Check(p.Finish(second,2048,1000,true,now.AddSeconds(4),4000) && p.Terminal && p.TotalOperations==4096 && p.TotalMilliseconds==2000,"exact finite aggregate cap");
        Check(p.TryBegin(Request(p,1),identity,now.AddSeconds(6),6000) is null,"no third/replay");
        foreach(var invalid in new[]{"nonce","batch","epoch","digest","order","schema","identity"}) {
            var bad=new FiniteRowsPolicy(Approval());var req=Request(bad);
            req=invalid switch { "nonce"=>req with{Nonce=Guid.NewGuid()},"batch"=>req with{BatchId=Guid.NewGuid()},
                "epoch"=>req with{PageEpoch=Guid.NewGuid()},"digest"=>req with{ApprovalSha256=new string('c',64)},
                "order"=>req with{ChunkIndex=1},"schema"=>req with{SchemaVersion=3},_=>req};
            Check(bad.TryBegin(req,invalid=="identity"?identity with{WindowScanStatus="truncated"}:identity,now,0) is null && bad.Terminal,"invalid attempt stops manifest");
            if(invalid=="identity") Check(bad.ChunksConsumed==1,"consume before identity failure");
        }
        foreach(var failure in new[]{"cooldown","replay","clock","utc","cancel","expiry","failure","overshoot","time","underreported","forged","stop"}) {
            var q=new FiniteRowsPolicy(Approval());var grant=q.TryBegin(Request(q),identity,now,10)!;
            if(failure is "cooldown" or "replay") {
                Check(q.Finish(grant,100,100,true,now.AddMilliseconds(100),110),"first fixture success");
                Check(q.TryBegin(Request(q,failure=="replay"?0:1),identity,now.AddSeconds(1),1010) is null && q.Terminal,"early/replayed admission terminal");continue;
            }
            if(failure=="clock") Check(!q.CheckActive(grant,now,9),"monotonic rollback");
            if(failure=="utc") Check(!q.CheckActive(grant,now.AddTicks(-1),10),"wallclock rollback");
            if(failure=="cancel") Check(!q.CheckActive(grant,now,10,new CancellationToken(true)),"cancel");
            if(failure=="expiry") Check(!q.CheckActive(grant,now.AddSeconds(120),120010),"expiry");
            if(failure=="forged") Check(!q.CheckActive(grant with{RowStart=2},now,10),"grant replacement");
            if(failure=="stop") q.Stop();
            var mono=failure=="underreported"?1011:110;
            Check(!q.Finish(grant,failure=="overshoot"?2049:100,failure=="time"?1001:100,failure!="failure",now.AddMilliseconds(100),mono) && q.Terminal,"failed output denied");
            Check(q.TotalOperations==(failure=="overshoot"?2049:100),"failed actual operations charged");
        }
        var pinned=new FiniteRowsPolicy(Approval());var pinnedFirst=pinned.TryBegin(Request(pinned),identity,now,0)!;
        Check(pinned.Finish(pinnedFirst,100,100,true,now.AddMilliseconds(100),100),"first window pinned");
        var replacement=identity with{WindowCandidates=new[]{identity.WindowCandidates![0] with{Hwnd=57}}};
        Check(pinned.TryBegin(Request(pinned,1),replacement,now.AddMilliseconds(2100),2100) is null && pinned.Terminal,
            "freshly valid replacement HWND cannot replace manifest window between chunks");
        Reject(Approval() with{Manifest="profile_custom"});
        foreach(var manifestName in new[]{"profile_rows0_3","profile_all_rows"}) {
            var extendedApproval=Approval() with{Manifest=manifestName};
            var extended=new FiniteRowsPolicy(extendedApproval);
            var count=manifestName=="profile_rows0_3"?6:18;
            Check(extended.MaximumDeclaredChunks==count && extended.MaximumDeclaredOperations==count*2048 &&
                extended.MaximumDeclaredMilliseconds==count*1000,"fixed per-manifest ceilings");
            Check(extended.NonceAt(0)==extendedApproval.FirstNonce && extended.NonceAt(1)==extendedApproval.SecondNonce,
                "first two approved nonces unchanged");
            var same=new FiniteRowsPolicy(extendedApproval);
            var nonces=Enumerable.Range(0,count).Select(extended.NonceAt).ToArray();
            Check(nonces.Distinct().Count()==count && nonces.SequenceEqual(Enumerable.Range(0,count).Select(same.NonceAt)),
                "derived nonces deterministic and distinct");
            var replaced=new FiniteRowsPolicy(extendedApproval with{BatchId=Guid.NewGuid()});
            Check(replaced.NonceAt(2)!=extended.NonceAt(2) && replaced.ApprovalSha256!=extended.ApprovalSha256,
                "derived child authorization cannot move to replacement batch");
            Check(new FiniteRowsPolicy(extendedApproval with{Manifest="goalkeeper_rows0_3"}).ApprovalSha256!=extended.ApprovalSha256,
                "manifest scope included in immutable approval digest");
            var expectedProfiles=FiniteCaptureSelection.ManifestProfiles(manifestName);
            var otherProfiles=FiniteCaptureSelection.ManifestProfiles(manifestName);otherProfiles[0]="modified";
            Check(expectedProfiles[0]=="goalkeeper_rows0_1","manifest arrays independently allocated");
            var totalRows=0;
            for(var index=0;index<count;index++) {
                var start=index*3000d;
                var req=new FiniteRowsRequest(4,extendedApproval.BatchId,extendedApproval.PageEpoch,index,extended.NonceAt(index),extended.ApprovalSha256);
                var chunk=extended.TryBegin(req,identity,now.AddMilliseconds(start),start)!;
                Check(chunk is not null && chunk.SelectionProfile==expectedProfiles[index] && chunk.MaximumOperations==2048 && chunk.MaximumMilliseconds==1000,
                    "fixed profile order and unchanged per-chunk caps");
                FiniteCaptureSelection.TryGet(chunk!.SelectionProfile,out var selection);
                Check(chunk.RowStart==selection.RowStart && chunk.RowCount==selection.RowCount,"manifest supplies selected row interval");
                totalRows+=chunk.RowCount;
                Check(extended.Finish(chunk,2048,1000,true,now.AddMilliseconds(start+1000),start+1000),"complete fixed chunk");
                Check(extended.Terminal==(index==count-1),"terminal only at fixed manifest end");
            }
            Check(totalRows==(count==18?35:12) && extended.TotalOperations==count*2048 && extended.TotalMilliseconds==count*1000,
                "exact complete manifest rows and global bounded accounting");
        }
        foreach(var pageManifest in new[]{"tactics_current","next_match_card","schedule_rows0_9"}) {
            var pageApproval=Approval() with{Manifest=pageManifest};
            var page=new FiniteRowsPolicy(pageApproval);
            var chunks=pageManifest=="schedule_rows0_9"?10:1;
            Check(page.MaximumDeclaredChunks==chunks && page.MaximumDeclaredOperations==chunks*2048 &&
                page.MaximumDeclaredMilliseconds==chunks*1000,"page-specific fixed limits without raising per-chunk limits");
            Check(new FiniteRowsPolicy(pageApproval with{Manifest="goalkeeper_rows0_3"}).ApprovalSha256!=page.ApprovalSha256,
                "page scope cannot reuse attribute authorization digest");
            for(var index=0;index<chunks;index++) {
                var expected=chunks==10?"schedule_row"+index.ToString(System.Globalization.CultureInfo.InvariantCulture):pageManifest;
                var time=index*3000d;
                var req=new FiniteRowsRequest(4,pageApproval.BatchId,pageApproval.PageEpoch,index,page.NonceAt(index),page.ApprovalSha256);
                var g=page.TryBegin(req,identity,now.AddMilliseconds(time),time)!;
                Check(g is not null && g.SelectionProfile==expected && g.MaximumOperations==2048 && g.MaximumMilliseconds==1000,
                    "one exact page/row selected in declared order");
                Check(page.Finish(g!,2048,1000,true,now.AddMilliseconds(time+1000),time+1000),"page chunk acknowledges only complete success");
                Check(page.Terminal==(index==chunks-1),"one-shot page terminal immediately; schedule terminates after ten");
            }
            Check(page.TotalOperations==chunks*2048 && page.TotalMilliseconds==chunks*1000 &&
                page.TryBegin(new(4,pageApproval.BatchId,pageApproval.PageEpoch,0,page.NonceAt(0),page.ApprovalSha256),identity,now.AddSeconds(40),40000) is null,
                "no page replay/implicit additional row after fixed completion");
            var wrongOrder=new FiniteRowsPolicy(pageApproval);
            Check(wrongOrder.TryBegin(new(4,pageApproval.BatchId,pageApproval.PageEpoch,1,pageApproval.SecondNonce,wrongOrder.ApprovalSha256),identity,now,0) is null && wrongOrder.Terminal,
                "page manifest cannot start at later chunk");
        }
        foreach(var invalidManifest in new[]{"tactics","schedule_row0","schedule_rows0_10","next_match","profile_custom"})
            Reject(Approval() with{Manifest=invalidManifest});
        var cap=new FiniteRowsPolicy(Approval());var active=cap.TryBegin(Request(cap),identity,now,0)!;
        Check(!cap.CheckActive(active,now.AddSeconds(1),1000) && cap.Terminal,"soft elapsed gate checked every child boundary");
    }
}

// Private browser proof; this is not a native-device qualification.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const folder = process.argv[2];
const { chromium, expect } = require(process.argv[3]);
const runtime = JSON.parse(fs.readFileSync(path.join(folder, "next-runtime-info.json")));
const origin = runtime.origin;
assert.equal(new URL(origin).hostname, "127.0.0.1");
const address = "a1".repeat(16);
(async () => {
    const browser = await chromium.launch();
    const proofs = [];
    try {
        for (const viewport of [{width:1280,height:960,name:"desktop"}, {width:390,height:844,name:"phone-viewport"}]) {
            const context = await browser.newContext({viewport, acceptDownloads:true});
            let blockedExternal = 0;
            await context.route("**/*", async route => {
                const target = new URL(route.request().url());
                if (target.origin !== origin) { ++blockedExternal; return route.abort(); }
                return route.continue({headers:{...route.request().headers(), "X-neXt-Session":runtime.capability}});
            });
            await context.routeWebSocket("**/*", route => {
                const expected = origin.replace(/^http:/,"ws:");
                if (new URL(route.url()).origin === expected) route.connectToServer();
                else { ++blockedExternal; route.close(); }
            });
            const page = await context.newPage();
            const failures = [];
            page.on("pageerror", error => failures.push(error.message));
            const headers = {"X-neXt-Session":runtime.capability};
            const csrf = await (await context.request.get(origin+"/api/v1/auth/csrf",{headers})).json();
            const post = async (suffix,data) => {
                const response = await context.request.post(origin+"/api/v1/"+suffix,
                    {headers:{...headers,"X-CSRF-Token":csrf.csrf_token,"Origin":origin},data});
                assert.equal(response.ok(),true,await response.text());
                return response.json();
            };
            if (!proofs.length) await post("telephone/contacts",{name:"Private UI Contact",lxmf_address:address});
            await page.goto(origin+"/#/messages",{waitUntil:"domcontentloaded"});
            const create = page.getByTitle("Create folder",{exact:true});
            await expect(create).toBeVisible({timeout:30000});
            await create.click();
            const prompt = page.locator('[aria-describedby="prompt-dialog-message"]');
            await expect(prompt).toBeVisible();
            const label = "Private "+viewport.name+" folder";
            await prompt.locator("input").fill(label);
            await prompt.getByRole("button",{name:"OK",exact:true}).click();
            await expect(page.getByText(label,{exact:true}).first()).toBeVisible();
            const list = await (await context.request.get(origin+"/api/v1/lxmf/folders",{headers})).json();
            const saved = list.find(row=>row.name===label);
            assert(saved,"Real UI must save its folder");
            const contact = page.getByText("Private UI Contact",{exact:true}).first();
            await expect(contact).toBeVisible();
            await contact.click({button:"right"});
            const pin = page.getByText(proofs.length ? "Unpin conversation" : "Pin conversation",{exact:true});
            await expect(pin).toBeVisible();
            await pin.click();
            let pinned = await (await context.request.get(origin+"/api/v1/lxmf/conversation-pins",{headers})).json();
            assert.deepEqual(pinned.peer_hashes,proofs.length ? [] : [address]);
            await contact.click({button:"right"});
            await page.getByText(label,{exact:true}).last().click();
            await page.reload({waitUntil:"domcontentloaded"});
            await expect(page.getByText(label,{exact:true}).first()).toBeVisible({timeout:30000});
            await page.getByText(label,{exact:true}).first().click();
            await expect(page.getByText("Private UI Contact",{exact:true}).first()).toBeVisible();
            const records = await (await context.request.get(origin+"/api/v1/lxmf/conversations?folder_id="+saved.id,{headers})).json();
            assert.equal(records.conversations[0].destination_hash,address);
            await page.screenshot({path:path.join(folder,viewport.name+".png"),fullPage:true});
            assert.deepEqual(failures,[],"The actual page must not throw during organization");
            proofs.push({viewport:viewport.name,folderCreatedThroughUI:true,pinToggledThroughUI:true,
                movedThroughUI:true,preservedAfterReload:true,noPageErrors:true,blockedExternal});
            await context.close();
        }
        fs.writeFileSync(path.join(folder,"proof.json"),JSON.stringify({browserOnly:true,radioAndTCPPeersOff:true,proofs},null,2)+"\n");
        console.log(JSON.stringify({browserOnly:true,proofs}));
    } catch (error) {
        for (const context of browser.contexts()) for (const page of context.pages()) {
            await page.screenshot({path:path.join(folder,"failure.png"),fullPage:true}).catch(()=>{});
            fs.writeFileSync(path.join(folder,"failure-body.txt"),await page.locator("body").innerText().catch(()=>""));
        }
        throw error;
    } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});

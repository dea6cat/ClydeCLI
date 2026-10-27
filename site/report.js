// The issue form: on submit, the version and system lines join the text, so GitHub's new-issue page opens with one filled-in body.
// Without this script the form still works: it sends the title, the label and the text as they are.
(function () {
  var form = document.getElementById("issue");
  if (!form) return;
  form.addEventListener("submit", function () {
    var what = document.getElementById("what"), version = document.getElementById("version").value.trim(), os = document.getElementById("os").value.trim();
    var facts = [];
    if (version) facts.push("**Clyde version:** " + version);
    if (os) facts.push("**System:** " + os);
    if (!facts.length) return;
    var body = document.createElement("input");
    body.type = "hidden"; body.name = "body"; body.value = what.value.trim() + "\n\n" + facts.join("\n") + "\n\n_Sent from the ClydeCLI site's report form._";
    what.removeAttribute("name");
    form.appendChild(body);
    // the form opens in a new tab: put the page back so a second submit starts from the same state
    setTimeout(function () { what.name = "body"; body.remove(); }, 0);
  });
})();

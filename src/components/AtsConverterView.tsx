import { useState } from "react";
import { CheckCircle2, Download, FileSpreadsheet, FileText, Loader2 } from "lucide-react";
import { convertToAtsPdfs } from "@/lib/api";

export function AtsConverterView() {
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [isConverting, setIsConverting] = useState(false);
  const [error, setError] = useState("");
  const [generatedCount, setGeneratedCount] = useState<number | null>(null);

  const convert = async () => {
    if (!csvFile) return;
    setIsConverting(true);
    setError("");
    setGeneratedCount(null);
    try {
      const result = await convertToAtsPdfs(csvFile);
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = result.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setGeneratedCount(result.count);
    } catch (conversionError) {
      setError(conversionError instanceof Error ? conversionError.message : "Conversion failed");
    } finally {
      setIsConverting(false);
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto space-y-6 py-4 md:py-8">
      <div>
        <h2 className="text-2xl font-bold text-foreground">ATS CV Converter</h2>
        <p className="text-sm text-muted-foreground">
          Convert candidate form exports into clean, searchable, ATS-friendly PDF resumes.
        </p>
      </div>

      <div className="rounded-2xl border bg-card shadow-card p-6 md:p-8 space-y-6">
        <div className="rounded-xl border bg-muted/30 p-5 md:p-6 flex gap-3">
          <FileText className="w-5 h-5 text-teal-600 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="text-sm font-semibold text-foreground">One PDF per candidate</p>
            <p className="text-xs text-muted-foreground leading-relaxed">
              The converter recognizes the form headers in your CSV, organizes experience,
              education, skills, certifications, and training, then downloads every generated
              resume in one ZIP file.
            </p>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-semibold text-foreground flex items-center gap-2">
            <FileSpreadsheet className="w-4 h-4 text-muted-foreground" />
            Candidate data (CSV)
          </label>
          <input
            type="file"
            accept=".csv,text/csv"
            disabled={isConverting}
            onChange={(event) => {
              setCsvFile(event.target.files?.[0] ?? null);
              setGeneratedCount(null);
              setError("");
            }}
            className="w-full text-sm file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-muted file:text-foreground hover:file:bg-muted/80 disabled:opacity-50"
          />
          {csvFile && (
            <p className="text-xs text-teal-600 flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5" />
              {csvFile.name}
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={convert}
          disabled={!csvFile || isConverting}
          className="w-full px-4 py-2.5 text-sm font-semibold rounded-lg teal-gradient text-white shadow-teal hover:opacity-90 disabled:opacity-60 transition-opacity flex items-center justify-center gap-2"
        >
          {isConverting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Creating ATS PDFs...
            </>
          ) : (
            <>
              <Download className="w-4 h-4" />
              Convert and Download PDFs
            </>
          )}
        </button>

        {generatedCount !== null && (
          <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-xs text-green-700 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            Generated {generatedCount} ATS PDF{generatedCount === 1 ? "" : "s"} successfully.
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

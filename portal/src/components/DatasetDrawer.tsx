import { useMatch, useNavigate } from "@tanstack/react-router";
import { Drawer } from "@base-ui/react/drawer";
import { Tabs } from "@base-ui/react/tabs";
import { useEffect, useState } from "react";
import {
  CalendarIcon,
  ArrowTopRightOnSquareIcon,
  DocumentDuplicateIcon,
  CheckIcon,
  XMarkIcon,
  GlobeAltIcon,
} from "@heroicons/react/24/outline";
import { LicenseBadge } from "./Badges";
import { formatDate } from "#/utils/formatters";
import { m } from "#/paraglide/messages";
import { cn } from "#/utils/cn";
import { card, devider, stats, button } from "#/utils/surfaces";
import type { Dataset } from "#/integrations/instantsearch/dataset-detail";

export function DatasetDrawer() {
  const navigate = useNavigate();

  const match = useMatch({
    from: "/_search/view/$",
    shouldThrow: false,
  });

  const isOpen = Boolean(match);

  const [dataset, setDataset] = useState<Dataset | null>(match?.loaderData?.dataset ?? null);

  useEffect(() => {
    if (match?.loaderData?.dataset) {
      setDataset(match.loaderData.dataset);
    }
  }, [match?.loaderData?.dataset]);

  return (
    <Drawer.Root
      open={isOpen}
      swipeDirection="right"
      onOpenChange={(open) => {
        if (!open) navigate({ to: "/" });
      }}
    >
      <Drawer.Portal>
        <Drawer.Backdrop
          className="
            fixed inset-0 bg-gray-950/20 backdrop-blur-sm
            transition-opacity duration-300
            data-ending-style:opacity-0 data-starting-style:opacity-0
          "
        />

        <Drawer.Viewport className="fixed inset-y-0 right-0 z-50 flex">
          <Drawer.Popup
            className={cn(
              card,
              "p-0 h-full w-screen max-w-2xl overflow-y-auto rounded-r-none shadow-2xl transition-[translate,opacity] duration-300 ease-out data-starting-style:translate-x-full data-ending-style:translate-x-full",
            )}
          >
            {dataset && (
              <Drawer.Content>
                <DatasetDetails dataset={dataset} isDrawer />
              </Drawer.Content>
            )}
          </Drawer.Popup>
        </Drawer.Viewport>
      </Drawer.Portal>
    </Drawer.Root>
  );
}

/* Content wrapper */
export function DatasetDetails({ dataset, isDrawer }: { dataset: Dataset; isDrawer?: boolean }) {
  return (
    <>
      {isDrawer ? (
        <Header dataset={dataset} />
      ) : (
        <div className="space-y-8 px-8 pt-8 pb-0">
          <h1 className="text-2xl font-bold mb-2">{dataset.title}</h1>
          <div className="mt-3 flex flex-wrap gap-2">
            {dataset.licence && <LicenseBadge license={dataset.licence} />}
          </div>
        </div>
      )}
      <div className="p-4 space-y-4 md:space-y-8 md:p-8">
        <CtaAndStats dataset={dataset} />

        {dataset.description && (
          <section>
            <SectionTitle>{m.description()}</SectionTitle>
            {isDrawer ? (
              <Drawer.Description className="mb-1 text-sm">
                {dataset.description}
              </Drawer.Description>
            ) : (
              <p className="text-sm">{dataset.description}</p>
            )}
          </section>
        )}
        <DetailTabs dataset={dataset} />
      </div>
    </>
  );
}

/* Header */
function Header({ dataset }: { dataset: Dataset }) {
  return (
    <div
      className={cn(
        devider,
        "sticky top-0 z-10 border-b bg-white-100/90 dark:bg-gray-950/90 px-4 md:px-8 py-4 md:py-6 backdrop-blur",
      )}
    >
      <div className="flex justify-between gap-6">
        <div>
          <Drawer.Title className="text-2xl font-semibold tracking-tight">
            {dataset.title}
          </Drawer.Title>

          <div className="mt-3 flex flex-wrap gap-2">
            {dataset.licence && <LicenseBadge license={dataset.licence} />}
          </div>
        </div>

        <Drawer.Close
          className="
            flex shrink-0 items-center justify-center
            rounded-full transition
            hover:text-cyan-500 
            cursor-pointer
            hover:scale-120
            active:scale-95
          "
        >
          <XMarkIcon className="size-8" />
        </Drawer.Close>
      </div>
    </div>
  );
}

/* ------------------------------ CTA + quick stats ------------------------------ */
function CtaAndStats({ dataset }: { dataset: Dataset }) {
  return (
    <section className="space-y-4">
      <a
        href={dataset.dataset_url ?? (dataset.doi ? `https://doi.org/${dataset.doi}` : "#")}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(button, "w-full")}
      >
        {m.goToDatasetSource()}
        <ArrowTopRightOnSquareIcon className="size-4" />
      </a>

      <div className="grid grid-cols-3 gap-3">
        <StatTile
          icon={<CalendarIcon className="size-4" />}
          label={m.deposited()}
          value={formatDate(dataset.published_at) ?? "—"}
        />
        <StatTile
          icon={<CalendarIcon className="size-4" />}
          label={m.interviewedDate()}
          value={formatDate(dataset.interview_date) ?? "—"}
        />
        <StatTile
          icon={<GlobeAltIcon className="size-4" />}
          label={m.language()}
          value={dataset.language_interview?.map((lang) => lang).join(", ") ?? "—"}
        />
      </div>
    </section>
  );
}

function StatTile({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className={cn(stats)}>
      <div className="flex items-center gap-1.5 text-gray-400">
        {icon}
        <span className="text-[11px] font-medium uppercase tracking-wide">{label}</span>
      </div>
      <div className="mt-1 text-sm font-semibold">{value}</div>
    </div>
  );
}

/* ---------------------------------- Tabs ---------------------------------- */
function DetailTabs({ dataset }: { dataset: Dataset }) {
  return (
    <Tabs.Root defaultValue="people" className="w-full">
      <Tabs.List className={cn("relative z-1 flex gap-6 border-b", devider)}>
        <TabTrigger value="people">{m.people()}</TabTrigger>
        <TabTrigger value="locationDate">{m.locationDate()}</TabTrigger>
        <TabTrigger value="classification">{m.classification()}</TabTrigger>
        <TabTrigger value="access">{m.rightsAndAccess()}</TabTrigger>
        <TabTrigger value="identifiers">{m.identifiers()}</TabTrigger>

        <Tabs.Indicator
          className="
            absolute bottom-0 left-0 z-10 h-0.5 rounded-full bg-cyan-500
            transition-[translate,width] duration-200 ease-in-out
            translate-x-(--active-tab-left)
            w-(--active-tab-width)
          "
        />
      </Tabs.List>

      <Tabs.Panel value="people" className="mt-6">
        <PeoplePanel dataset={dataset} />
      </Tabs.Panel>

      <Tabs.Panel value="locationDate" className="mt-6">
        <LocationDatePanel dataset={dataset} />
      </Tabs.Panel>

      <Tabs.Panel value="classification" className="mt-6">
        <ClassificationPanel dataset={dataset} />
      </Tabs.Panel>

      <Tabs.Panel value="access" className="mt-6">
        <AccessPanel dataset={dataset} />
      </Tabs.Panel>

      <Tabs.Panel value="identifiers" className="mt-6">
        <IdentifiersPanel dataset={dataset} />
      </Tabs.Panel>
    </Tabs.Root>
  );
}

function TabTrigger({ value, children }: { value: string; children: React.ReactNode }) {
  return (
    <Tabs.Tab
      value={value}
      className="
        relative -mb-px cursor-pointer
        py-3 text-sm font-medium text-gray-400
        transition-colors
        hover:text-gray-700
        dark:hover:text-gray-300
        data-active:text-gray-950
        dark:data-active:text-gray-50
        focus-visible:outline-none
      "
    >
      {children}
    </Tabs.Tab>
  );
}

/* --------------------------------- Panels --------------------------------- */
function PeoplePanel({ dataset }: { dataset: Dataset }) {
  return (
    <div className="space-y-5">
      {dataset.authors?.length ? (
        <PanelGroup title={m.authors()}>
          <div className="flex flex-wrap gap-2">
            {dataset.authors.map((a, i) => (
              <Chip key={a}>
                {a}
                {dataset.author_affiliations ? ` (${dataset.author_affiliations[i]})` : ""}
              </Chip>
            ))}
          </div>
        </PanelGroup>
      ) : null}

      {dataset.interviewee ? (
        <PanelGroup title={m.interviewee()}>
          <div className="flex flex-wrap gap-2">
            <Chip>
              {dataset.interviewee}
              {dataset.interviewee_affiliations ? ` (${dataset.interviewee_affiliations[0]})` : ""}
            </Chip>
          </div>
        </PanelGroup>
      ) : null}

      {dataset.interviewer ? (
        <PanelGroup title={m.interviewer()}>
          <div className="flex flex-wrap gap-2">
            <Chip>
              {dataset.interviewer}
              {dataset.interviewer_affiliations ? ` (${dataset.interviewer_affiliations[0]})` : ""}
            </Chip>
          </div>
        </PanelGroup>
      ) : null}

      {dataset.recorded_by?.length ? (
        <PanelGroup title={m.recordedBy()}>
          <div className="flex flex-wrap gap-2">
            {dataset.recorded_by.map((r, i) => (
              <Chip key={r}>
                {r}
                {dataset.recorded_by_affiliation ? ` (${dataset.recorded_by_affiliation[i]})` : ""}
              </Chip>
            ))}
          </div>
        </PanelGroup>
      ) : null}

      {dataset.others?.length ? (
        <PanelGroup title={m.others()}>
          <div className="flex flex-wrap gap-2">
            {dataset.others.map((r, i) => (
              <Chip key={r}>
                {r}
                {dataset.others_affiliations ? ` (${dataset.others_affiliations[i]})` : ""}
              </Chip>
            ))}
          </div>
        </PanelGroup>
      ) : null}

      {dataset.interpreter?.length ? (
        <PanelGroup title={m.interpreter()}>
          <div className="flex flex-wrap gap-2">
            {dataset.interpreter.map((r, i) => (
              <Chip key={r}>
                {r}
                {dataset.interpreter_affiliations
                  ? ` (${dataset.interpreter_affiliations[i]})`
                  : ""}
              </Chip>
            ))}
          </div>
        </PanelGroup>
      ) : null}

      {!dataset.authors?.length &&
        !dataset.interpreter?.length &&
        !dataset.others?.length &&
        !dataset.interviewee &&
        !dataset.recorded_by?.length &&
        !dataset.interviewer?.length && <EmptyState />}
    </div>
  );
}

function LocationDatePanel({ dataset }: { dataset: Dataset }) {
  console.log(dataset);
  return (
    <div className="space-y-5">
      {dataset.subject_locations?.length ? (
        <PanelGroup title={m.subjectLocations()}>
          <div className="flex flex-wrap gap-2">
            {dataset.subject_locations.map((r) => (
              <Chip key={r}>{r}</Chip>
            ))}
          </div>
        </PanelGroup>
      ) : null}

      {dataset.subject_year_start || dataset.subject_year_end ? (
        <MetadataRow
          label={m.subjectPeriod()}
          value={`${dataset.subject_year_start ?? ""}${dataset.subject_year_start && dataset.subject_year_end ? " - " : ""}${dataset.subject_year_end ?? ""}`}
        />
      ) : null}

      {dataset.interview_location?.length ? (
        <PanelGroup title={m.interviewLocation()}>
          <div className="flex flex-wrap gap-2">
            {dataset.interview_location.map((r) => (
              <Chip key={r}>{r}</Chip>
            ))}
          </div>
        </PanelGroup>
      ) : null}

      {dataset.interview_date || dataset.interview_date_end ? (
        <MetadataRow
          label={m.interviewedDate()}
          value={`${formatDate(dataset.interview_date) ?? ""}${dataset.interview_date && dataset.interview_date_end ? " - " : ""}${formatDate(dataset.interview_date_end) ?? ""}`}
        />
      ) : null}

      {dataset.recording_equipment ? (
        <MetadataRow label={m.recordingEquipment()} value={dataset.recording_equipment} />
      ) : null}

      {!dataset.subject_locations?.length &&
        !dataset.interview_location?.length &&
        !dataset.interview_date &&
        !dataset.interview_date_end &&
        !dataset.subject_year_start &&
        !dataset.subject_year_end &&
        !dataset.recording_equipment && <EmptyState />}
    </div>
  );
}

function ClassificationPanel({ dataset }: { dataset: Dataset }) {
  return (
    <div className="space-y-5">
      {dataset.subject_keywords?.length ? (
        <PanelGroup title={m.keywords()}>
          <div className="flex flex-wrap gap-2">
            {dataset.subject_keywords.map((a, i) => (
              <Chip
                key={a}
                link={dataset.subject_keyword_uri?.[i] ? dataset.subject_keyword_uri[i] : undefined}
              >
                {a}
              </Chip>
            ))}
          </div>
        </PanelGroup>
      ) : null}

      {dataset.audience?.length ? (
        <PanelGroup title={m.audienceClassification()}>
          <div className="flex flex-wrap gap-2">
            {dataset.audience.map((a, i) => (
              <Chip key={a} link={dataset.audience_uri?.[i] ? dataset.audience_uri[i] : undefined}>
                {a}
              </Chip>
            ))}
          </div>
        </PanelGroup>
      ) : null}

      {dataset.collections?.length ? (
        <PanelGroup title={m.collections()}>
          <div className="flex flex-wrap gap-2">
            {dataset.collections.map((a, i) => (
              <Chip
                key={a}
                link={dataset.collections_uri?.[i] ? dataset.collections_uri[i] : undefined}
              >
                {a}
              </Chip>
            ))}
          </div>
        </PanelGroup>
      ) : null}

      {!dataset.subject_keywords?.length &&
        !dataset.collections?.length &&
        !dataset.audience?.length && <EmptyState />}
    </div>
  );
}

function AccessPanel({ dataset }: { dataset: Dataset }) {
  return (
    <div className="space-y-3">
      <MetadataRow label={m.license()} value={dataset.licence} />
      <MetadataRow label={m.rightsHolders()} value={dataset.rightsholder} />
      <div className={cn(stats, "flex justify-between gap-4")}>
        <span className="text-sm text-gray-400">{m.personalDataPresent()}</span>
        <span
          className={`
            inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5
            text-xs font-semibold
            ${dataset.contains_personal_data ? "bg-rose-50 text-rose-700" : "bg-emerald-50 text-emerald-700"}
          `}
        >
          {dataset.contains_personal_data === true ? m.yes() : m.no()}
        </span>
      </div>
    </div>
  );
}

function IdentifiersPanel({ dataset }: { dataset: Dataset }) {
  return (
    <div className="space-y-3">
      {dataset.doi && <CopyableField label="DOI" value={dataset.doi} />}
    </div>
  );
}

/* -------------------------------- Primitives -------------------------------- */
function PanelGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">{title}</h3>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">
      {children}
    </h2>
  );
}

function MetadataRow({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className={cn(stats, "flex justify-between gap-4")}>
      <span className="text-sm text-gray-400">{label}</span>
      <span className="text-right text-sm font-medium">{value}</span>
    </div>
  );
}

function Chip({
  children,
  tone = "zinc",
  link,
}: {
  children: React.ReactNode;
  tone?: "zinc" | "cyan";
  link?: string;
}) {
  const styles =
    tone === "cyan"
      ? "bg-cyan-50 text-cyan-500 ring-cyan-500 dark:ring-cyan-700"
      : "ring-gray-200 dark:ring-gray-700";
  return link ? (
    <a
      href={link}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        stats,
        `py-1.5 inline-flex items-center text-xs font-medium ring-1 ring-inset ${styles} gap-1 transition hover:ring-cyan-300 `,
      )}
    >
      {children}
      <ArrowTopRightOnSquareIcon className="size-4" />
    </a>
  ) : (
    <span
      className={cn(
        stats,
        `py-1.5 inline-flex items-center text-xs font-medium ring-1 ring-inset ${styles}`,
      )}
    >
      {children}
    </span>
  );
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-gray-200 px-4 py-6 text-center text-xs text-gray-400">
      {m.noInformationAvailable()}
    </div>
  );
}

function CopyableField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className={cn(stats)}>
      <div className="text-[11px] font-medium uppercase tracking-wide text-gray-400">{label}</div>
      <div className="mt-1 flex items-center justify-between gap-3">
        <span className="truncate font-mono text-s">{value}</span>
        <button
          onClick={handleCopy}
          className="
            flex shrink-0 items-center gap-1 rounded-full px-2 py-1
            text-xs font-medium text-gray-400 transition
            hover:bg-gray-100 hover:text-gray-700
            cursor-pointer
          "
        >
          {copied ? <CheckIcon className="size-4" /> : <DocumentDuplicateIcon className="size-4" />}
          {copied ? m.copied() : m.copy()}
        </button>
      </div>
    </div>
  );
}

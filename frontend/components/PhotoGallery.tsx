"use client";

import { useEffect, useRef, useState } from "react";
import {
  deleteSymptomPhoto,
  fetchSymptomPhotoBlobUrl,
  listSymptomPhotos,
  SymptomPhoto,
  uploadSymptomPhoto,
} from "@/lib/api";

interface PhotoWithUrl extends SymptomPhoto {
  url: string;
}

interface Props {
  recordId: number;
  token: string;
  // Only the uploading patient can add/remove photos — a provider
  // viewing a panel patient's record gets a read-only gallery. See
  // backend/app/api/symptom_photos.py: upload/delete both require the
  // "patient" role AND ownership, enforced server-side regardless of
  // what this prop is set to — this only controls whether the UI
  // offers controls the API would reject anyway.
  canManage: boolean;
}

// Loads lazily (only once expanded), not on every audit-table row render
// — a provider's audit table can have 50 rows, and fetching photos for
// all of them up front would be 50 extra requests for a feature most
// rows don't even use.
export default function PhotoGallery({ recordId, token, canManage }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [photos, setPhotos] = useState<PhotoWithUrl[] | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const urlsRef = useRef<string[]>([]);

  useEffect(() => {
    // Revoke every blob: URL this component ever created when it
    // unmounts (e.g. the audit table row's gallery is collapsed and
    // this component is torn down) — otherwise each one leaks for the
    // rest of the tab's lifetime.
    return () => {
      urlsRef.current.forEach((u) => URL.revokeObjectURL(u));
    };
  }, []);

  async function load() {
    setError(null);
    try {
      const list = await listSymptomPhotos(token, recordId);
      const withUrls = await Promise.all(
        list.map(async (p) => {
          const url = await fetchSymptomPhotoBlobUrl(token, recordId, p.id);
          urlsRef.current.push(url);
          return { ...p, url };
        })
      );
      setPhotos(withUrls);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load photos");
    }
  }

  function toggle() {
    const next = !expanded;
    setExpanded(next);
    if (next && photos === null) load();
  }

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file next time
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await uploadSymptomPhoto(token, recordId, file);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(photoId: number) {
    setError(null);
    try {
      await deleteSymptomPhoto(token, recordId, photoId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  return (
    <div className="photo-gallery">
      <button type="button" className="photo-gallery-toggle" onClick={toggle}>
        {expanded ? "Hide photos" : "Photos"}
      </button>

      {expanded && (
        <div className="photo-gallery-body">
          {error && <p className="auth-error">{error}</p>}

          {photos === null && !error && <p className="photo-gallery-loading">Loading…</p>}

          {photos !== null && (
            <div className="photo-gallery-grid">
              {photos.map((p) => (
                <div key={p.id} className="photo-gallery-item">
                  <img src={p.url} alt="Patient-submitted symptom photo" />
                  {canManage && (
                    <button
                      type="button"
                      className="photo-gallery-delete"
                      onClick={() => handleDelete(p.id)}
                      aria-label="Delete photo"
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
              {photos.length === 0 && (
                <p className="photo-gallery-empty">No photos attached.</p>
              )}
            </div>
          )}

          {canManage && (
            <div className="photo-gallery-upload">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={handleFileSelected}
                disabled={uploading}
              />
              {uploading && <span>Uploading…</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

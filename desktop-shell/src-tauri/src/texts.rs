//! Operator-facing shell messages in the panel's language (uz / ru / en).
//!
//! The panel keeps its language in `DATA\desktop_state.json` (`ui.lang`); the
//! shell reads the same value so the splash and message boxes match it.

use std::path::Path;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Lang {
    En,
    Ru,
    Uz,
}

pub fn lang(data_dir: &Path) -> Lang {
    let raw = std::fs::read(data_dir.join("desktop_state.json")).unwrap_or_default();
    let value: serde_json::Value = serde_json::from_slice(&raw).unwrap_or_default();
    match value["ui"]["lang"].as_str().map(str::to_ascii_lowercase).as_deref() {
        Some("ru") => Lang::Ru,
        Some("uz") => Lang::Uz,
        _ => Lang::En,
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Msg {
    Starting,
    Database,
    Preparing,
    Ready,
    Stopping,
    StillStarting,
    CheckingUpdates,
    DownloadingUpdate,
    InstallingUpdate,
    AlreadyRunning,
    CouldNotStart,
    TryAgain,
    BackendStopped,
    BackendKeepsStopping,
    QuitWarning,
    QuitQuestion,
    UpToDate,
    InstallQuestion,
    UpdateCouldNotStart,
    WebView2Missing,
    TrayOpen,
    TrayUpdate,
    TrayQuit,
}

pub fn text(lang: Lang, msg: Msg) -> &'static str {
    use Lang::*;
    use Msg::*;
    match (msg, lang) {
        (Starting, En) => "Starting Alpha POS…",
        (Starting, Ru) => "Запуск Alpha POS…",
        (Starting, Uz) => "Alpha POS ishga tushmoqda…",
        (Database, En) => "Starting the database…",
        (Database, Ru) => "Запуск базы данных…",
        (Database, Uz) => "Ma’lumotlar bazasi ishga tushmoqda…",
        (Preparing, En) => "Preparing the POS server…",
        (Preparing, Ru) => "Подготовка POS-сервера…",
        (Preparing, Uz) => "POS server tayyorlanmoqda…",
        (Ready, En) => "Ready",
        (Ready, Ru) => "Готово",
        (Ready, Uz) => "Tayyor",
        (Stopping, En) => "Stopping…",
        (Stopping, Ru) => "Остановка…",
        (Stopping, Uz) => "To‘xtatilmoqda…",
        (StillStarting, En) => "Still starting — retrying…",
        (StillStarting, Ru) => "Всё ещё запускается — повторяем…",
        (StillStarting, Uz) => "Hali ishga tushmoqda — qayta urinilmoqda…",
        (CheckingUpdates, En) => "Checking for updates…",
        (CheckingUpdates, Ru) => "Проверка обновлений…",
        (CheckingUpdates, Uz) => "Yangilanishlar tekshirilmoqda…",
        (DownloadingUpdate, En) => "Downloading update",
        (DownloadingUpdate, Ru) => "Загрузка обновления",
        (DownloadingUpdate, Uz) => "Yangilanish yuklab olinmoqda",
        (InstallingUpdate, En) => "Installing update",
        (InstallingUpdate, Ru) => "Установка обновления",
        (InstallingUpdate, Uz) => "Yangilanish o‘rnatilmoqda",
        (AlreadyRunning, En) => "Alpha POS is already running on this computer, or its previous copy is still closing. Wait a minute and open it again.",
        (AlreadyRunning, Ru) => "Alpha POS уже запущен на этом компьютере или предыдущая копия ещё закрывается. Подождите минуту и откройте снова.",
        (AlreadyRunning, Uz) => "Alpha POS bu kompyuterda allaqachon ishlayapti yoki oldingi nusxasi hali yopilmoqda. Bir daqiqa kutib, qayta oching.",
        (CouldNotStart, En) => "Alpha POS could not start.",
        (CouldNotStart, Ru) => "Не удалось запустить Alpha POS.",
        (CouldNotStart, Uz) => "Alpha POS ishga tushmadi.",
        (TryAgain, En) => "Try again now?",
        (TryAgain, Ru) => "Попробовать ещё раз?",
        (TryAgain, Uz) => "Qayta urinib ko‘rilsinmi?",
        (BackendStopped, En) => "The POS server stopped unexpectedly and is being restarted…",
        (BackendStopped, Ru) => "POS-сервер неожиданно остановился и перезапускается…",
        (BackendStopped, Uz) => "POS server kutilmaganda to‘xtadi va qayta ishga tushirilmoqda…",
        (BackendKeepsStopping, En) => "The POS server keeps stopping. Alpha POS keeps restarting it. If this continues, restart the computer and contact support.",
        (BackendKeepsStopping, Ru) => "POS-сервер постоянно останавливается. Alpha POS продолжает его перезапускать. Если это повторяется, перезагрузите компьютер и обратитесь в поддержку.",
        (BackendKeepsStopping, Uz) => "POS server to‘xtab qolmoqda. Alpha POS uni qayta ishga tushirishda davom etadi. Bu takrorlansa, kompyuterni qayta ishga tushiring va yordam xizmatiga murojaat qiling.",
        (QuitWarning, En) => "The POS server will stop: waiters, couriers and other devices cannot place orders until Alpha POS is running again.",
        (QuitWarning, Ru) => "POS-сервер остановится: официанты, курьеры и другие устройства не смогут принимать заказы, пока Alpha POS снова не запустится.",
        (QuitWarning, Uz) => "POS server to‘xtaydi: Alpha POS qayta ishga tushmaguncha ofitsiantlar, kuryerlar va boshqa qurilmalar buyurtma qabul qila olmaydi.",
        (QuitQuestion, En) => "Quit Alpha POS?",
        (QuitQuestion, Ru) => "Закрыть Alpha POS?",
        (QuitQuestion, Uz) => "Alpha POS yopilsinmi?",
        (UpToDate, En) => "Alpha POS is up to date. New versions are downloaded automatically.",
        (UpToDate, Ru) => "Alpha POS обновлён. Новые версии загружаются автоматически.",
        (UpToDate, Uz) => "Alpha POS eng so‘nggi versiyada. Yangi versiyalar avtomatik yuklab olinadi.",
        (InstallQuestion, En) => "Install Alpha POS {version} now? It restarts by itself when the update is installed.",
        (InstallQuestion, Ru) => "Установить Alpha POS {version} сейчас? Программа перезапустится сама после установки.",
        (InstallQuestion, Uz) => "Alpha POS {version} hozir o‘rnatilsinmi? O‘rnatilgach, dastur o‘zi qayta ishga tushadi.",
        (UpdateCouldNotStart, En) => "The update could not be started. Alpha POS keeps running; please try again later.",
        (UpdateCouldNotStart, Ru) => "Не удалось начать обновление. Alpha POS продолжает работать; попробуйте позже.",
        (UpdateCouldNotStart, Uz) => "Yangilashni boshlab bo‘lmadi. Alpha POS ishlashda davom etadi; keyinroq qayta urinib ko‘ring.",
        (WebView2Missing, En) => "Alpha POS needs the Microsoft Edge WebView2 Runtime, which is missing on this computer.\n\nConnect to the internet and run the Alpha POS installer again, or install \"WebView2 Runtime\" from microsoft.com.",
        (WebView2Missing, Ru) => "Для Alpha POS нужен Microsoft Edge WebView2 Runtime, но на этом компьютере его нет.\n\nПодключитесь к интернету и снова запустите установщик Alpha POS или установите «WebView2 Runtime» с сайта microsoft.com.",
        (WebView2Missing, Uz) => "Alpha POS uchun Microsoft Edge WebView2 Runtime kerak, lekin u bu kompyuterda yo‘q.\n\nInternetga ulaning va Alpha POS o‘rnatuvchisini qayta ishga tushiring yoki microsoft.com saytidan «WebView2 Runtime»ni o‘rnating.",
        (TrayOpen, En) => "Open Alpha POS",
        (TrayOpen, Ru) => "Открыть Alpha POS",
        (TrayOpen, Uz) => "Alpha POS ni ochish",
        (TrayUpdate, En) => "Restart to update",
        (TrayUpdate, Ru) => "Перезапустить для обновления",
        (TrayUpdate, Uz) => "Yangilash uchun qayta ishga tushirish",
        (TrayQuit, En) => "Quit Alpha POS",
        (TrayQuit, Ru) => "Закрыть Alpha POS",
        (TrayQuit, Uz) => "Alpha POS ni yopish",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_the_panel_language_and_defaults_to_english() {
        let dir = std::env::temp_dir().join(format!("alphapos-texts-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        assert_eq!(lang(&dir), Lang::En);
        std::fs::write(dir.join("desktop_state.json"), r#"{"ui": {"lang": "uz"}}"#).unwrap();
        assert_eq!(lang(&dir), Lang::Uz);
        std::fs::write(dir.join("desktop_state.json"), "not json").unwrap();
        assert_eq!(lang(&dir), Lang::En);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn install_question_has_a_version_slot_in_every_language() {
        for lang in [Lang::En, Lang::Ru, Lang::Uz] {
            assert!(text(lang, Msg::InstallQuestion).contains("{version}"));
        }
    }
}
